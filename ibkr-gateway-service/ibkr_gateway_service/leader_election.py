import logging
import threading
import time
import os
import uuid # For unique identity if pod name not available
import random # For jitter
from typing import Callable

from kubernetes import client, config as kube_config # Renamed to avoid conflict with local config
from kubernetes.client.rest import ApiException

logger = logging.getLogger(__name__)

class LeaderElector:
    def __init__(self,
                 lease_name: str,
                 lease_namespace: str,
                 identity: Optional[str], # Pod name is ideal
                 on_started_leading: Callable[[], None],
                 on_stopped_leading: Callable[[], None],
                 lease_duration_seconds: int = 15,
                 renew_deadline_seconds: int = 10, # How long before lease expiry to try renew
                 retry_period_seconds: int = 2    # How often to retry acquiring/renewing
                ):
        self.lease_name = lease_name
        self.lease_namespace = lease_namespace

        if identity:
            self.identity = identity
        else:
            # Fallback if pod name isn't easily available via env var
            self.identity = str(uuid.uuid4())
            logger.warning(f"LeaderElector: Identity not provided, generated a UUID: {self.identity}. Pod name is preferred.")

        self.on_started_leading = on_started_leading
        self.on_stopped_leading = on_stopped_leading

        self.is_leader = False
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None

        try:
            kube_config.load_incluster_config() # For running inside K8s
            logger.info("LeaderElector: Loaded in-cluster Kubernetes config.")
        except kube_config.ConfigException:
            try:
                kube_config.load_kube_config() # For local testing
                logger.info("LeaderElector: Loaded local Kubeconfig.")
            except kube_config.ConfigException as e:
                logger.error(f"LeaderElector: Could not load Kubernetes configuration: {e}")
                raise  # Cannot operate without K8s config

        self.coordination_v1_api = client.CoordinationV1Api()
        self.lease_duration_seconds = lease_duration_seconds
        self.renew_deadline_factor = float(renew_deadline_seconds) / float(lease_duration_seconds) # e.g. 10/15 = 0.66
        self.retry_period_seconds = retry_period_seconds

        # Ensure lease duration is greater than renew deadline
        if renew_deadline_seconds >= lease_duration_seconds:
            logger.warning(f"Lease renew deadline ({renew_deadline_seconds}s) >= lease duration ({lease_duration_seconds}s). Adjusting deadline.")
            self.renew_deadline_factor = 0.66 # Default to 2/3 of duration
            # Actual renew_deadline_seconds = self.lease_duration_seconds * self.renew_deadline_factor


    def _try_acquire_or_renew_lease(self):
        try:
            lease = self.coordination_v1_api.read_namespaced_lease(self.lease_name, self.lease_namespace)

            now_utc = datetime.utcnow().replace(tzinfo=timezone.utc) # Use timezone-aware UTC now
            now_micro_time = client.V1MicroTime(now_utc) # K8s client expects V1MicroTime

            if lease.spec.holder_identity == self.identity:
                # We are the leader, renew
                lease.spec.renew_time = now_micro_time
                # lease.spec.lease_transitions = (lease.spec.lease_transitions or 0) + 1 # K8s client might not like this direct int manipulation
                self.coordination_v1_api.replace_namespaced_lease(self.lease_name, self.lease_namespace, lease)
                logger.debug(f"LeaderElector [{self.identity}]: Renewed lease.")
                if not self.is_leader: # Should not happen if holder_identity is self, but good check
                    logger.info(f"LeaderElector [{self.identity}]: Transitioned to leader (on renew).")
                    self.is_leader = True
                    self.on_started_leading()
                return True
            else:
                # Check if current lease is expired
                lease_expired = False
                if lease.spec.renew_time and lease.spec.lease_duration_seconds:
                    # Expiry time = renew_time + lease_duration_seconds
                    renew_time_dt = lease.spec.renew_time.replace(tzinfo=timezone.utc) # Assume stored as UTC
                    expiry_time = renew_time_dt + timedelta(seconds=lease.spec.lease_duration_seconds)
                    if now_utc > expiry_time:
                        lease_expired = True
                        logger.info(f"LeaderElector [{self.identity}]: Lease held by {lease.spec.holder_identity} found to be expired (expiry: {expiry_time}, now: {now_utc}).")

                if lease.spec.holder_identity is None or lease_expired:
                    # Try to acquire
                    logger.info(f"LeaderElector [{self.identity}]: Attempting to acquire lease (previous holder: {lease.spec.holder_identity}, expired: {lease_expired}).")
                    lease.spec.holder_identity = self.identity
                    lease.spec.lease_duration_seconds = self.lease_duration_seconds
                    lease.spec.acquire_time = now_micro_time
                    lease.spec.renew_time = now_micro_time
                    # lease.spec.lease_transitions = (lease.spec.lease_transitions or 0) + 1
                    self.coordination_v1_api.replace_namespaced_lease(self.lease_name, self.lease_namespace, lease)
                    logger.info(f"LeaderElector [{self.identity}]: Acquired leadership.")
                    if not self.is_leader:
                        self.is_leader = True
                        self.on_started_leading()
                    return True
                else: # Another instance is the leader and lease is active
                    if self.is_leader: # We were leader but lost it (e.g. due to network partition and our lease expired)
                        logger.warning(f"LeaderElector [{self.identity}]: Lost leadership to {lease.spec.holder_identity}.")
                        self.is_leader = False
                        self.on_stopped_leading()
                    # else: logger.debug(f"LeaderElector [{self.identity}]: Lease held by {lease.spec.holder_identity}.")
                    return False

        except ApiException as e:
            if e.status == 404: # Lease doesn't exist, try to create
                try:
                    now_utc = datetime.utcnow().replace(tzinfo=timezone.utc)
                    now_micro_time = client.V1MicroTime(now_utc)
                    lease_body = client.V1Lease(
                        api_version="coordination.k8s.io/v1",
                        kind="Lease",
                        metadata={"name": self.lease_name, "namespace": self.lease_namespace},
                        spec=client.V1LeaseSpec(
                            holder_identity=self.identity,
                            lease_duration_seconds=self.lease_duration_seconds,
                            acquire_time=now_micro_time,
                            renew_time=now_micro_time,
                            # lease_transitions=0
                        )
                    )
                    self.coordination_v1_api.create_namespaced_lease(self.lease_namespace, lease_body)
                    logger.info(f"LeaderElector [{self.identity}]: Created and acquired lease.")
                    if not self.is_leader:
                        self.is_leader = True
                        self.on_started_leading()
                    return True
                except ApiException as create_e:
                    logger.error(f"LeaderElector [{self.identity}]: Failed to create lease: {create_e}")
            elif e.status == 409: # Conflict, someone else acquired/updated
                 logger.debug(f"LeaderElector [{self.identity}]: Conflict trying to update lease, likely another instance acted faster.")
            else:
                logger.error(f"LeaderElector [{self.identity}]: Error interacting with lease API: {e}")

            if self.is_leader: # If any error occurred while we thought we were leader
                self.is_leader = False
                self.on_stopped_leading()
            return False
        except Exception as e_general: # Catch other potential errors like time parsing
            logger.error(f"LeaderElector [{self.identity}]: General exception in _try_acquire_or_renew_lease: {e_general}", exc_info=True)
            if self.is_leader:
                self.is_leader = False
                self.on_stopped_leading()
            return False


    def _run_election_loop(self):
        logger.info(f"LeaderElector [{self.identity}]: Starting election loop.")
        while not self._stop_event.is_set():
            acquired_or_renewed = self._try_acquire_or_renew_lease()

            # Determine sleep duration
            sleep_duration = self.retry_period_seconds
            if self.is_leader and acquired_or_renewed:
                # If leader, sleep for a duration that ensures timely renewal
                # e.g., 1/3 of lease_duration, but not less than retry_period
                renew_check_interval = float(self.lease_duration_seconds) * (1.0 - self.renew_deadline_factor) * 0.5 # Renew proactively
                if renew_check_interval < self.retry_period_seconds:
                    sleep_duration = max(1, int(renew_check_interval)) # Ensure at least 1s
                else:
                    sleep_duration = self.retry_period_seconds


            # Add jitter to sleep_duration to prevent thundering herd
            jitter_factor = (random.random() * 0.5) - 0.25 # Jitter between -25% and +25%
            final_sleep_duration = sleep_duration + (jitter_factor * float(sleep_duration))
            if final_sleep_duration < 0.1: final_sleep_duration = 0.1 # Min sleep 100ms

            # logger.debug(f"LeaderElector [{self.identity}]: IsLeader={self.is_leader}. Sleeping for {final_sleep_duration:.2f}s.")
            self._stop_event.wait(final_sleep_duration)

        logger.info(f"LeaderElector [{self.identity}]: Election loop stopped.")
        if self.is_leader: # Ensure on_stopped_leading is called if stopped while leader
            logger.info(f"LeaderElector [{self.identity}]: Stepping down as leader due to stop signal.")
            self.is_leader = False
            self.on_stopped_leading()
            # Optionally try to release the lease by setting holderIdentity to null
            # This is good practice but not strictly required by K8s leader election protocol
            try:
                lease = self.coordination_v1_api.read_namespaced_lease(self.lease_name, self.lease_namespace)
                if lease.spec.holder_identity == self.identity:
                    lease.spec.holder_identity = "" # Release the lease
                    # lease.spec.lease_transitions = (lease.spec.lease_transitions or 0) + 1
                    self.coordination_v1_api.replace_namespaced_lease(self.lease_name, self.lease_namespace, lease)
                    logger.info(f"LeaderElector [{self.identity}]: Released lease on stop.")
            except ApiException as e:
                logger.error(f"LeaderElector [{self.identity}]: Error releasing lease on stop: {e}")
            except Exception as e_gen:
                 logger.error(f"LeaderElector [{self.identity}]: General error releasing lease on stop: {e_gen}", exc_info=True)


    def start(self):
        if self._thread and self._thread.is_alive():
            logger.warning(f"LeaderElector [{self.identity}]: Election loop already running.")
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run_election_loop, name=f"LeaderElector-{self.identity[:8]}", daemon=True)
        self._thread.start()

    def stop(self):
        logger.info(f"LeaderElector [{self.identity}]: Stop requested.")
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=self.retry_period_seconds * 2) # Wait for loop to exit
            if self._thread.is_alive():
                logger.warning(f"LeaderElector [{self.identity}]: Election loop thread did not stop gracefully.")
        logger.info(f"LeaderElector [{self.identity}]: Stopped.")

    def get_is_leader(self) -> bool:
        return self.is_leader

# Need to add imports for datetime, timedelta, timezone from datetime module
# from datetime import datetime, timedelta, timezone
# This will be added at the top of the file.
