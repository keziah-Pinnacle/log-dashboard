import streamlit as st
import pandas as pd
from datetime import datetime
import plotly.graph_objects as go
import re  # For extracting camera ID

# Page config
st.set_page_config(page_title="Log Dashboard", layout="wide")

# Title
st.title("Log Dashboard")

# File uploader - supports multiple
uploaded_files = st.file_uploader("Upload log files (plain .txt from your cameras)", type="txt", accept_multiple_files=True)

if len(uploaded_files) > 0:
    # Note about pagination
    if len(uploaded_files) > 10:
        st.info(f"📁 Uploaded {len(uploaded_files)} files. Pagination below is normal—each session processes only current uploads.")
    
    # Parse all files
    all_data = []
    unique_cameras = set()
    for uploaded_file in uploaded_files:
        filename = uploaded_file.name
        log_content = uploaded_file.read().decode('utf-8')
        lines = log_content.strip().split('\n')
        
        # Extract camera from filename (e.g., PR7-007120 → 007120) or ID
        camera_match = re.search(r'(\d{6})', filename)
        default_camera = camera_match.group(1) if camera_match else 'Unknown'
        
        for line in lines:
            line = line.strip()
            if not line or '#' not in line:
                continue
            try:
                parts = line.split('#')
                timestamp_str = parts[0].strip()
                event_parts = [p.strip() for p in parts[2:] if p.strip()]
                full_event = ' '.join(event_parts) if event_parts else 'Unknown'
                
                # Normalize event: remove battery level for grouping
                normalized_event = full_event.split(' - Battery Level - ')[0].strip() if ' - Battery Level - ' in full_event else full_event
                
                # Parse timestamp
                dt = datetime.strptime(timestamp_str, '%Y-%m-%d %H:%M:%S')
                
                # Extract battery
                battery = None
                if 'Battery Level -' in full_event:
                    battery_str = full_event.split('Battery Level -')[-1].strip().rstrip('%').strip()
                    try:
                        battery = int(battery_str)
                    except:
                        pass
                
                # Extract camera from line if possible (e.g., #ID:007120-000000)
                id_match = re.search(r'#ID:(\d{6})-\d{6}', line)
                camera = id_match.group(1) if id_match else default_camera
                unique_cameras.add(camera)
                
                all_data.append({
                    'timestamp': dt,
                    'event': full_event,
                    'normalized_event': normalized_event,
                    'battery': battery,
                    'camera': camera
                })
            except:
                continue
    
    if not all_data:
        st.error("No valid log entries found. Check file format.")
    else:
        df = pd.DataFrame(all_data)
        df = df.sort_values('timestamp')
        
        # Camera filter
        selected_cameras = st.multiselect("Choose Camera ID", options=sorted(list(unique_cameras)), default=list(unique_cameras))
        filtered_df = df[df['camera'].isin(selected_cameras)]
        
        # Battery Graph with colored background zones
        st.subheader("Battery Levels Over Time")
        if filtered_df['battery'].notna().any():
            fig = go.Figure()
            
            # Add background color zones
            fig.add_trace(go.Scatter(
                x=[filtered_df['timestamp'].min(), filtered_df['timestamp'].max()],
                y=[0, 20],
                fill='tozeroy',
                fillcolor='rgba(255, 0, 0, 0.2)',  # Red zone (0-20%)
                line=dict(color='rgba(255, 0, 0, 0)'),
                name='Critical (0-20%)',
                showlegend=True
            ))
            fig.add_trace(go.Scatter(
                x=[filtered_df['timestamp'].min(), filtered_df['timestamp'].max()],
                y=[20, 65],
                fill='tozeroy',
                fillcolor='rgba(255, 165, 0, 0.2)',  # Amber zone (20-65%)
                line=dict(color='rgba(255, 165, 0, 0)'),
                name='Caution (20-65%)',
                showlegend=True
            ))
            fig.add_trace(go.Scatter(
                x=[filtered_df['timestamp'].min(), filtered_df['timestamp'].max()],
                y=[65, 100],
                fill='tozeroy',
                fillcolor='rgba(0, 255, 0, 0.2)',  # Green zone (>65%)
                line=dict(color='rgba(0, 255, 0, 0)'),
                name='Good (>65%)',
                showlegend=True
            ))
            
            # Battery line with markers
            valid_df = filtered_df.dropna(subset=['battery'])
            fig.add_trace(go.Scatter(
                x=valid_df['timestamp'],
                y=valid_df['battery'],
                mode='lines+markers',
                line=dict(color='black', width=2),  # Bold black line to highlight levels
                marker=dict(size=8, line=dict(width=1, color='darkgray')),
                name='Battery %',
                hovertemplate='<b>%{x}</b><br>Battery: %{y}%<br>Camera: ' + valid_df['camera'] + '<extra></extra>'
            ))
            
            fig.update_layout(
                title='Battery Levels (Red: 0-20%, Amber: 20-65%, Green: >65%)',
                xaxis_title='Date',
                yaxis_title='Battery Level (%)',
                yaxis=dict(range=[0, 100], tickformat='.0f'),
                height=400,
                hovermode='x unified',
                legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1)
            )
            
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.warning("No battery data for selected cameras.")
        
        # Main Events (summarized key events with non-tech names)
        st.subheader("Key Activities")
        compressed_events = []
        if not filtered_df.empty:
            current_norm_event = filtered_df.iloc[0]['normalized_event']
            current_camera = filtered_df.iloc[0]['camera']
            start_time = filtered_df.iloc[0]['timestamp']
            batteries = [filtered_df.iloc[0]['battery']] if pd.notna(filtered_df.iloc[0]['battery']) else []
            end_time = start_time
            
            for i in range(1, len(filtered_df)):
                row = filtered_df.iloc[i]
                if row['normalized_event'] == current_norm_event and row['camera'] == current_camera:
                    end_time = row['timestamp']
                    if pd.notna(row['battery']):
                        batteries.append(row['battery'])
                else:
                    # Compress and rename events
                    event_name = {
                        'Battery Charging': 'Charging Session',
                        'System Power On': 'Device Turned On',
                        'System Power Off': 'Device Turned Off',
                        'Start Record': 'Recording Started',
                        'Stop Record': 'Recording Stopped',
                        'Low Battery': 'Low Battery Alert',
                        'Battery Empty': 'Battery Depleted',
                        'Battery Changing Done': 'Charging Completed'
                    }.get(current_norm_event, current_norm_event)
                    
                    if batteries:
                        min_bat = min(batteries)
                        max_bat = max(batteries)
                        battery_range = f"{int(min_bat)}% - {int(max_bat)}%" if min_bat != max_bat else f"{int(min_bat)}%"
                    else:
                        battery_range = "N/A"
                    duration = (end_time - start_time).total_seconds() / 60
                    compressed_events.append({
                        'Start Time': start_time.strftime('%Y-%m-%d %H:%M:%S'),
                        'End Time': end_time.strftime('%Y-%m-%d %H:%M:%S'),
                        'Camera': current_camera,
                        'Activity': event_name,
                        'Battery Level': battery_range,
                        'Duration (min)': f"{duration:.1f}"
                    })
                    current_norm_event = row['normalized_event']
                    current_camera = row['camera']
                    start_time = row['timestamp']
                    batteries = [row['battery']] if pd.notna(row['battery']) else []
                    end_time = start_time
            
            # Last group
            event_name = {
                'Battery Charging': 'Charging Session',
                'System Power On': 'Device Turned On',
                'System Power Off': 'Device Turned Off',
                'Start Record': 'Recording Started',
                'Stop Record': 'Recording Stopped',
                'Low Battery': 'Low Battery Alert',
                'Battery Empty': 'Battery Depleted',
                'Battery Changing Done': 'Charging Completed'
            }.get(current_norm_event, current_norm_event)
            if batteries:
                min_bat = min(batteries)
                max_bat = max(batteries)
                battery_range = f"{int(min_bat)}% - {int(max_bat)}%" if min_bat != max_bat else f"{int(min_bat)}%"
            else:
                battery_range = "N/A"
            duration = (end_time - start_time).total_seconds() / 60
            compressed_events.append({
                'Start Time': start_time.strftime('%Y-%m-%d %H:%M:%S'),
                'End Time': end_time.strftime('%Y-%m-%d %H:%M:%S'),
                'Camera': current_camera,
                'Activity': event_name,
                'Battery Level': battery_range,
                'Duration (min)': f"{duration:.1f}"
            })
        
        events_df = pd.DataFrame(compressed_events)
        st.dataframe(events_df, use_container_width=True, hide_index=True)
        
        # Recent Activities (alerts and critical points only)
        st.subheader("Alerts & Issues")
        activity_df = filtered_df.copy()
        activity_df['Status'] = activity_df['normalized_event'].apply(lambda e: '⚠️ Warning' if 'Low Battery' in e or 'Battery Empty' in e else '🔴 Error' if 'Error' in e else None)
        activity_df = activity_df.dropna(subset=['Status'])  # Only show rows with alerts
        if not activity_df.empty:
            activity_df['Activity'] = activity_df['normalized_event'].apply(lambda e: {
                'Low Battery': 'Low Battery Alert',
                'Battery Empty': 'Battery Depleted',
                'Error': 'System Error'
            }.get(e.split(' - ')[0], e))
            activity_cols = ['timestamp', 'camera', 'Activity', 'battery', 'Status']
            activity_display = activity_df[activity_cols].tail(50)  # Last 50 alerts
            activity_display.columns = ['Time', 'Camera', 'Alert', 'Battery %', 'Status']
            st.dataframe(activity_display, use_container_width=True, hide_index=True)
        else:
            st.success("No alerts or issues detected.")
        
        # Overall Summary
        st.subheader("Quick Overview")
        if not filtered_df.empty:
            date_range = f"{filtered_df['timestamp'].min().strftime('%Y-%m-%d')} to {filtered_df['timestamp'].max().strftime('%Y-%m-%d')}"
            total_events = len(filtered_df)
            unique_events = filtered_df['normalized_event'].nunique()
            min_battery = filtered_df['battery'].min()
            max_battery = filtered_df['battery'].max()
            avg_battery = filtered_df['battery'].mean()
            
            power_ons = len(filtered_df[filtered_df['normalized_event'].str.contains('Power On', na=False)])
            power_offs = len(filtered_df[filtered_df['normalized_event'].str.contains('Power Off', na=False)])
            charging_sessions = len(filtered_df[filtered_df['normalized_event'].str.contains('Battery Charging', na=False)])
            low_battery_count = len(filtered_df[filtered_df['battery'] <= 20])
            
            summary = f"""
            **Time Frame:** {date_range}
            
            **At a Glance:**
            - Total log entries: {total_events}
            - Different events: {unique_events}
            - Battery range: {min_battery:.0f}% to {max_battery:.0f}% (average: {avg_battery:.0f}%)
            
            **Key Moments:**
            - Device Turned On: {power_ons} times
            - Device Turned Off: {power_offs} times
            - Charging sessions: {charging_sessions}
            - Low battery alerts (≤20%): {low_battery_count}
            
            **What Happened:**
            The device was active during this time, turning on and off as needed.
            Battery {'dropped low' if min_battery <= 20 else 'stayed mostly stable'}.
            Charging happened {'a few times' if charging_sessions > 1 else 'once'}, keeping it full.
            No major problems unless alerts show up below.
            """
            st.markdown(summary)
        else:
            st.warning("No data for selected cameras.")
else:
    st.info("Upload .txt log files to start tracking your cameras.")
    # Example
    example_data = {
        'Start Time': ['2025-09-03 01:24:56', '2025-09-03 08:12:05'],
        'End Time': ['2025-09-03 02:15:36', '2025-09-03 08:12:05'],
        'Camera': ['007120', '007490'],
        'Activity': ['Charging Session', 'Device Turned Off'],
        'Battery Level': ['92% - 100%', '100%'],
        'Duration (min)': ['50.7', '0.0']
    }
    st.subheader("Example Key Activities")
    st.dataframe(pd.DataFrame(example_data))