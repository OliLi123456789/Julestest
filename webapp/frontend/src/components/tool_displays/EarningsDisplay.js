// webapp/frontend/src/components/tool_displays/EarningsDisplay.js
import React from 'react';

// Basic styling
const earningsDisplayContainerStyle = {
    borderTop: '1px dashed #ddd',
    marginTop: '10px',
    paddingTop: '10px'
};
const earningsItemStyle = {
    border: '1px solid #eee', padding: '10px', marginBottom: '10px',
    borderRadius: '5px', backgroundColor: '#f9f9f9'
};
const symbolStyle = { fontWeight: 'bold', fontSize: '1.1em', marginBottom: '5px' };

function formatLargeNumber(num) { // Helper for revenue
    if (num === null || num === undefined || isNaN(parseFloat(num))) return 'N/A';
    num = parseFloat(num);
    if (Math.abs(num) >= 1e9) return (num / 1e9).toFixed(2) + 'B';
    if (Math.abs(num) >= 1e6) return (num / 1e6).toFixed(2) + 'M';
    if (Math.abs(num) >= 1e3) return (num / 1e3).toFixed(2) + 'K';
    return num.toString();
}

function EarningsDisplay({ reports }) { // reports is List[EarningsReportResponse]
    if (!reports || reports.length === 0) {
        return <p>No earnings reports to display.</p>;
    }

    return (
        <div style={earningsDisplayContainerStyle} className="earnings-display-container">
            <h5 style={{ marginTop: '0', marginBottom: '10px' }}>Earnings Reports:</h5>
            {reports.map((report, index) => (
                <div key={report.id || `${report.symbol}-${report.report_date}` || index} style={earningsItemStyle}>
                    <p style={symbolStyle}>
                        {report.symbol || 'N/A'} -
                        Reported: {report.report_date ? new Date(report.report_date).toLocaleDateString() : 'N/A'}
                        ({report.time_of_day || 'N/A'})
                    </p>
                    <p>Fiscal Period Ending: {report.fiscal_period_ending || 'N/A'}</p>
                    <p>
                        EPS Actual: {report.eps_actual !== null && report.eps_actual !== undefined ? report.eps_actual.toFixed(2) : 'N/A'} |
                        EPS Estimate: {report.eps_estimate !== null && report.eps_estimate !== undefined ? report.eps_estimate.toFixed(2) : 'N/A'}
                        {report.eps_actual !== null && report.eps_actual !== undefined && report.eps_estimate !== null && report.eps_estimate !== undefined && (
                            <span style={{color: report.eps_actual >= report.eps_estimate ? 'green' : 'red', marginLeft: '5px'}}>
                                ({report.eps_actual >= report.eps_estimate ? 'Beat' : 'Miss'})
                            </span>
                        )}
                    </p>
                    <p>
                        Revenue Actual: {formatLargeNumber(report.revenue_actual)} |
                        Revenue Estimate: {formatLargeNumber(report.revenue_estimate)}
                    </p>
                </div>
            ))}
        </div>
    );
}
export default EarningsDisplay;
