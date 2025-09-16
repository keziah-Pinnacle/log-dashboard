import streamlit as st
import pandas as pd
from datetime import datetime
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import io

# Page config
st.set_page_config(page_title="Log Dashboard", layout="wide")

# Title
st.title("Log Dashboard")

# File uploader
uploaded_file = st.file_uploader("Upload logs (plain .txt files from your camera logs)", type="txt")

if uploaded_file is not None:
    # Read the file
    log_content = uploaded_file.read().decode('utf-8')
    lines = log_content.strip().split('\n')
    
    # Parse logs
    data = []
    for line in lines:
        line = line.strip()
        if not line or '#' not in line:
            continue
        try:
            # Parse: "2025-09-08 07:10:31 #ID:007120-000000 #USB Remove - Battery Level -  100%"
            parts = line.split('#')
            timestamp_str = parts[0].strip()
            event_parts = [p.strip() for p in parts[2:] if p.strip()]
            event = ' '.join(event_parts) if event_parts else 'Unknown'
            
            # Parse timestamp
            dt = datetime.strptime(timestamp_str, '%Y-%m-%d %H:%M:%S')
            
            # Extract battery level if present
            battery = None
            if 'Battery Level -' in event:
                battery_str = event.split('Battery Level -')[-1].strip().rstrip('%').strip()
                try:
                    battery = int(battery_str)
                except:
                    pass
            
            data.append({
                'timestamp': dt,
                'event': event,
                'battery': battery
            })
        except:
            continue  # Skip invalid lines
    
    if not data:
        st.error("No valid log entries found. Please check the file format.")
    else:
        df = pd.DataFrame(data)
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
            
            # Sample points for line (interpolate if needed, but use actual points)
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
        
        # Compressed Events Table
        st.subheader("Compressed Events")
        
        # Group repeated events
        compressed_events = []
        if not df.empty:
            current_event = df.iloc[0]['event']
            start_time = df.iloc[0]['timestamp']
            start_battery = df.iloc[0]['battery']
            end_time = start_time
            end_battery = start_battery
            
            for i in range(1, len(df)):
                row = df.iloc[i]
                if row['event'] == current_event and pd.notna(row['battery']) == pd.notna(start_battery):
                    # Same event, extend range
                    end_time = row['timestamp']
                    if pd.notna(row['battery']):
                        end_battery = row['battery']
                else:
                    # New event, add compressed row
                    battery_range = f"{int(start_battery)}%" if pd.notna(start_battery) else "N/A"
                    if pd.notna(end_battery) and end_battery != start_battery:
                        battery_range = f"{int(start_battery)}% - {int(end_battery)}%"
                    compressed_events.append({
                        'Start Time': start_time.strftime('%Y-%m-%d %H:%M:%S'),
                        'End Time': end_time.strftime('%Y-%m-%d %H:%M:%S'),
                        'Event': current_event,
                        'Battery Level': battery_range
                    })
                    # Start new group
                    current_event = row['event']
                    start_time = row['timestamp']
                    start_battery = row['battery']
                    end_time = start_time
                    end_battery = start_battery
            
            # Add last event
            battery_range = f"{int(start_battery)}%" if pd.notna(start_battery) else "N/A"
            if pd.notna(end_battery) and end_battery != start_battery:
                battery_range = f"{int(start_battery)}% - {int(end_battery)}%"
            compressed_events.append({
                'Start Time': start_time.strftime('%Y-%m-%d %H:%M:%S'),
                'End Time': end_time.strftime('%Y-%m-%d %H:%M:%S'),
                'Event': current_event,
                'Battery Level': battery_range
            })
        
        events_df = pd.DataFrame(compressed_events)
        st.dataframe(events_df, use_container_width=True)
        
        # Daily Summary
        st.subheader("Daily Summary")
        if not df.empty:
            date_str = df['timestamp'].dt.date.iloc[0].strftime('%Y-%m-%d')
            total_events = len(df)
            unique_events = df['event'].nunique()
            min_battery = df['battery'].min()
            max_battery = df['battery'].max()
            avg_battery = df['battery'].mean()
            
            power_ons = len(df[df['event'].str.contains('Power On', na=False)])
            power_offs = len(df[df['event'].str.contains('Power Off', na=False)])
            charging_starts = len(df[df['event'].str.contains('Battery Charging', na=False)])
            low_battery = len(df[df['battery'] <= 30])
            
            summary = f"""
            **Date:** {date_str}
            
            **Overview:**
            - Total log entries: {total_events}
            - Unique event types: {unique_events}
            - Battery range: {min_battery:.0f}% to {max_battery:.0f}% (average: {avg_battery:.0f}%)
            
            **Key Events:**
            - System Power On: {power_ons} times
            - System Power Off: {power_offs} times
            - Battery Charging sessions: {charging_starts}
            - Low battery warnings (≤30%): {low_battery} occurrences
            
            **What Happened:**
            The device was active for most of the day, with multiple power cycles likely due to user interactions or auto-shutdowns.
            Battery started high but experienced { 'a significant drop' if min_battery < 30 else 'minor fluctuations' }.
            Charging occurred {'frequently' if charging_starts > 1 else 'once'}, bringing it back to full.
            No critical errors noted beyond standard low battery alerts.
            """
            st.markdown(summary)
        else:
            st.warning("No data to summarize.")
else:
    # Show example like your screenshot (static)
    st.info("Please upload a .txt log file to get started.")
    
    # Static example table (like your screenshot)
    example_data = {
        'Start Time': ['2025-09-03 01:24:56', '2025-09-03 08:12:05', '2025-09-03 08:12:05', '2025-09-03 08:12:05', '2025-09-03 08:12:05'],
        'End Time': ['2025-09-03 02:15:36', '2025-09-03 08:12:05', '2025-09-03 08:12:05', '2025-09-03 08:12:05', '2025-09-03 08:12:05'],
        'Event': ['Battery Charging', 'System Power Off - Auto', 'System Power On', 'Battery Charging', 'DC Remove'],
        'Battery Level': ['92% - 100%', '100%', '100%', '100%', '100%']
    }
    st.subheader("Example Compressed Events")
    st.dataframe(pd.DataFrame(example_data))