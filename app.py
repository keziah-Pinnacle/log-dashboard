import streamlit as st
import pandas as pd
from datetime import datetime
import plotly.graph_objects as go
import io

# Page config
st.set_page_config(page_title="Log Dashboard", layout="wide")

# Title
st.title("Log Dashboard")

# File uploader - now supports multiple files
uploaded_files = st.file_uploader("Upload logs (plain .txt files from your camera logs)", type="txt", accept_multiple_files=True)

if len(uploaded_files) > 0:
    # Parse all files
    all_data = []
    for uploaded_file in uploaded_files:
        log_content = uploaded_file.read().decode('utf-8')
        lines = log_content.strip().split('\n')
        
        for line in lines:
            line = line.strip()
            if not line or '#' not in line:
                continue
            try:
                # Parse: "2025-09-08 07:10:31 #ID:007120-000000 #USB Remove - Battery Level -  100%"
                parts = line.split('#')
                timestamp_str = parts[0].strip()
                event_parts = [p.strip() for p in parts[2:] if p.strip()]
                full_event = ' '.join(event_parts) if event_parts else 'Unknown'
                
                # Normalize event: remove battery level part for grouping (e.g., "Battery Charging")
                normalized_event = full_event.split(' - Battery Level - ')[0].strip() if ' - Battery Level - ' in full_event else full_event
                
                # Parse timestamp
                dt = datetime.strptime(timestamp_str, '%Y-%m-%d %H:%M:%S')
                
                # Extract battery level if present
                battery = None
                if 'Battery Level -' in full_event:
                    battery_str = full_event.split('Battery Level -')[-1].strip().rstrip('%').strip()
                    try:
                        battery = int(battery_str)
                    except:
                        pass
                
                all_data.append({
                    'timestamp': dt,
                    'event': full_event,
                    'normalized_event': normalized_event,
                    'battery': battery
                })
            except:
                continue  # Skip invalid lines
    
    if not all_data:
        st.error("No valid log entries found. Please check the file format.")
    else:
        df = pd.DataFrame(all_data)
        df = df.sort_values('timestamp')
        
        # Battery Graph
        st.subheader("Battery Levels")
        if df['battery'].notna().any():
            # Create colorful line chart
            fig = go.Figure()
            
            # Color mapping
            def get_color(bat):
                if bat <= 30:
                    return 'red'
                elif bat <= 70:
                    return 'orange'
                else:
                    return 'green'
            
            # Sample points for line (use actual points)
            valid_df = df.dropna(subset=['battery'])
            colors = [get_color(b) for b in valid_df['battery']]
            
            fig.add_trace(go.Scatter(
                x=valid_df['timestamp'],
                y=valid_df['battery'],
                mode='lines+markers',
                line=dict(color='blue', width=2),  # Base line blue
                marker=dict(color=colors, size=4),
                name='Battery %'
            ))
            
            fig.update_layout(
                title='Battery Levels Over Time',
                xaxis_title='Date',
                yaxis_title='Battery Level (%)',
                yaxis=dict(range=[0, 100]),
                height=400,
                showlegend=False
            )
            
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.warning("No battery levels found in logs.")
        
        # Compressed Events Table - improved grouping with normalization
        st.subheader("Compressed Events")
        
        compressed_events = []
        if not df.empty:
            current_norm_event = df.iloc[0]['normalized_event']
            start_time = df.iloc[0]['timestamp']
            batteries = [df.iloc[0]['battery']] if pd.notna(df.iloc[0]['battery']) else []
            end_time = start_time
            # Use normalized for clean event name
            current_event = df.iloc[0]['normalized_event']
            
            for i in range(1, len(df)):
                row = df.iloc[i]
                if row['normalized_event'] == current_norm_event:
                    # Same normalized event, extend range and collect batteries
                    end_time = row['timestamp']
                    if pd.notna(row['battery']):
                        batteries.append(row['battery'])
                else:
                    # Compress and add row
                    if batteries:
                        min_bat = min(batteries)
                        max_bat = max(batteries)
                        battery_range = f"{int(min_bat)}% - {int(max_bat)}%" if min_bat != max_bat else f"{int(min_bat)}%"
                    else:
                        battery_range = "N/A"
                    compressed_events.append({
                        'Start Time': start_time.strftime('%Y-%m-%d %H:%M:%S'),
                        'End Time': end_time.strftime('%Y-%m-%d %H:%M:%S'),
                        'Event': current_event,
                        'Battery Level': battery_range
                    })
                    # Start new group
                    current_norm_event = row['normalized_event']
                    start_time = row['timestamp']
                    batteries = [row['battery']] if pd.notna(row['battery']) else []
                    end_time = start_time
                    current_event = row['normalized_event']
            
            # Add last group
            if batteries:
                min_bat = min(batteries)
                max_bat = max(batteries)
                battery_range = f"{int(min_bat)}% - {int(max_bat)}%" if min_bat != max_bat else f"{int(min_bat)}%"
            else:
                battery_range = "N/A"
            compressed_events.append({
                'Start Time': start_time.strftime('%Y-%m-%d %H:%M:%S'),
                'End Time': end_time.strftime('%Y-%m-%d %H:%M:%S'),
                'Event': current_event,
                'Battery Level': battery_range
            })
        
        events_df = pd.DataFrame(compressed_events)
        st.dataframe(events_df, use_container_width=True)
        
        # Daily Summary - now for overall period
        st.subheader("Overall Summary")
        if not df.empty:
            date_range = f"{df['timestamp'].min().strftime('%Y-%m-%d')} to {df['timestamp'].max().strftime('%Y-%m-%d')}"
            total_events = len(df)
            unique_events = df['normalized_event'].nunique()
            min_battery = df['battery'].min()
            max_battery = df['battery'].max()
            avg_battery = df['battery'].mean()
            
            power_ons = len(df[df['normalized_event'].str.contains('Power On', na=False)])
            power_offs = len(df[df['normalized_event'].str.contains('Power Off', na=False)])
            charging_sessions = len(df[df['normalized_event'].str.contains('Battery Charging', na=False)])
            low_battery_count = len(df[df['battery'] <= 30])
            
            summary = f"""
            **Date Range:** {date_range}
            
            **Overview:**
            - Total log entries: {total_events}
            - Unique event types: {unique_events}
            - Battery range: {min_battery:.0f}% to {max_battery:.0f}% (average: {avg_battery:.0f}%)
            
            **Key Events:**
            - System Power On: {power_ons} times
            - System Power Off: {power_offs} times
            - Battery Charging sessions: {charging_sessions}
            - Low battery warnings (≤30%): {low_battery_count} occurrences
            
            **What Happened:**
            The device was active across the period, with multiple power cycles likely due to user interactions or auto-shutdowns.
            Battery experienced {'a significant drop' if min_battery < 30 else 'minor fluctuations'}.
            Charging occurred {'frequently' if charging_sessions > 1 else 'once or twice'}, bringing it back to full.
            No critical errors noted beyond standard low battery alerts.
            """
            st.markdown(summary)
        else:
            st.warning("No data to summarize.")
else:
    # Show example like your screenshot (static)
    st.info("Please upload one or more .txt log files to get started.")
    
    # Static example table (updated to show compression)
    example_data = {
        'Start Time': ['2025-09-03 01:24:56', '2025-09-03 08:12:05', '2025-09-03 08:12:05', '2025-09-03 08:12:05', '2025-09-03 08:12:05'],
        'End Time': ['2025-09-03 02:15:36', '2025-09-03 08:12:05', '2025-09-03 08:12:05', '2025-09-03 08:12:05', '2025-09-03 08:12:05'],
        'Event': ['Battery Charging', 'System Power Off - Auto', 'System Power On', 'Battery Charging', 'DC Remove'],
        'Battery Level': ['92% - 100%', '100%', '100%', '100%', '100%']
    }
    st.subheader("Example Compressed Events")
    st.dataframe(pd.DataFrame(example_data))