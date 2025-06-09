import React from 'react';

function ChartDisplay({ symbol }) {
  return (
    <div style={{ border: '1px solid #ccc', padding: '20px', margin: '10px 0' }}>
      <h3>Chart for: {symbol || 'No Symbol Selected'}</h3>
      <div style={{ height: '300px', display: 'flex', alignItems: 'center', justifyContent: 'center', backgroundColor: '#f0f0f0' }}>
        <p>[Chart Placeholder]</p>
      </div>
    </div>
  );
}

export default ChartDisplay;
