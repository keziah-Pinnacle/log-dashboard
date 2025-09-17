import streamlit as st
import pandas as pd
from datetime import datetime
import plotly.graph_objects as go
import re  # For extracting camera ID
from io import BytesIO
import base64

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
            
            # Add background color zones (vertical fill)
            fig.add_trace(go.Scatter(
                x=[filtered_df['timestamp'].min(), filtered_df['timestamp'].max()],
                y=[0, 20],
                fill='tozeroy',
                fillcolor='rgba(139, 0, 0, 0.4)',  # Dark red (0-20%)
                line=dict(color='rgba(139, 0, 0, 0)'),
                name='Critical (0-20%)',
                showlegend=True
            ))
            fig.add_trace(go.Scatter(
                x=[filtered_df['timestamp'].min(), filtered_df['timestamp'].max()],
                y=[20, 60],
                fill='tozeroy',
                fillcolor='rgba(255, 165, 0, 0.4)',  # Orange (20-60%)
                line=dict(color='rgba(255, 165, 0, 0)'),
                name='Caution (20-60%)',
                showlegend=True
            ))
            fig.add_trace(go.Scatter(
                x=[filtered_df['timestamp'].min(), filtered_df['timestamp'].max()],
                y=[60, 100],
                fill='tozeroy',
                fillcolor='rgba(0, 100, 0, 0.4)',  # Dark green (60-100%)
                line=dict(color='rgba(0, 100, 0, 0)'),
                name='Good (60-100%)',
                showlegend=True
            ))
            
            # Battery line with markers
            valid_df = filtered_df.dropna(subset=['battery']).reset_index(drop=True)
            # Create event_map and duration_map as Series
            event_map = valid_df['normalized_event'].shift().fillna('None') + ' → ' + valid_df['normalized_event']
            duration_map = valid_df['timestamp'].diff().fillna(pd.Timedelta(0)).dt.total_seconds() / 60  # Fixed: Use timestamp diff
            
            fig.add_trace(go.Scatter(
                x=valid_df['timestamp'],
                y=valid_df['battery'],
                mode='lines+markers',
                line=dict(color='black', width=2),
                marker=dict(size=8, line=dict(width=1, color='darkgray')),
                name='Battery %',
                hovertemplate=
                '<b>%{x}</b><br>' +
                'Battery: %{y}%<br>' +
                'Camera: %{customdata[0]}<br>' +
                'Event: %{customdata[1]}<br>' +
                'Pre-Event: %{customdata[2]}<br>' +
                'Duration: %{customdata[3]:.1f} min<extra></extra>',
                customdata=valid_df[['camera', 'normalized_event', event_map, duration_map]].values
            ))
            
            fig.update_layout(
                title='Battery Levels (Dark Red: 0-20%, Orange: 20-60%, Dark Green: 60-100%)',
                xaxis_title='Date',
                yaxis_title='Battery Level (%)',
                yaxis=dict(range=[0, 100], tickformat='.0f'),
                height=400,
                hovermode='x unified',
                legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1)
            )
            
            st.plotly_chart(fig, use_container_width=True)
            
            # Export PDF button
            buffer = BytesIO()
            fig.write_image(buffer, format='pdf', engine='kaleido')
            buffer.seek(0)
            b64 = base64.b64encode(buffer.read()).decode()
            href = f'<a href="data:application/pdf;base64,{b64}" download="battery_report.pdf" target="_blank">📄 Download Graph as PDF</a>'
            st.markdown(href, unsafe_allow_html=True)
            
        else:
            st.warning("No battery data for selected cameras.")
        
        # Graph Summary for non-tech users
        st.subheader("Battery Usage Summary")
        if filtered_df['battery'].notna().any():
            power_on_df = filtered_df[filtered_df['normalized_event'].str.contains('Power On', na=False)]
            recording_start_df = filtered_df[filtered_df['normalized_event'].str.contains('Start Record', na=False)]
            charging_df = filtered_df[filtered_df['normalized_event'].str.contains('Battery Charging', na=False)]
            
            summary_text = "Here's what happened with the battery:\n\n"
            if not power_on_df.empty:
                summary_text += f"- Device turned on {len(power_on_df)} times, starting with battery levels from {int(power_on_df['battery'].min())}% to {int(power_on_df['battery'].max())}%.\n"
            if not recording_start_df.empty:
                summary_text += f"- Recording started {len(recording_start_df)} times, with battery between {int(recording_start_df['battery'].min())}% and {int(recording_start_df['battery'].max())}%.\n"
            if not charging_df.empty:
                summary_text += f"- Charging happened {len(charging_df)} times, boosting battery when it was as low as {int(charging_df['battery'].min())}%.\n"
            total_usage = len(filtered_df) - len(filtered_df[filtered_df['battery'].isna()])
            summary_text += f"- Total battery checks: {total_usage}. The battery {'stayed healthy' if filtered_df['battery'].min() > 20 else 'had low points'}."
            st.markdown(summary_text)
        else:
            st.warning("No battery data to summarize.")
        
        # Key Activities (summarized key events with non-tech names)
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
        
        # Alerts & Issues (critical points only)
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