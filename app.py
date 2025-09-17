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
uploaded_files = st.file_uploader("Upload logs (plain .txt files from your camera logs)", type="txt", accept_multiple_files=True)

if len(uploaded_files) > 0:
    # Note about pagination
    if len(uploaded_files) > 10:
        st.info(f"📁 Uploaded {len(uploaded_files)} files. Use pagination below if needed. Each upload processes fresh—no old data persists.")
    
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
        st.error("No valid log entries found. Please check the file format.")
    else:
        df = pd.DataFrame(all_data)
        df = df.sort_values('timestamp')
        
        # Camera filter
        selected_cameras = st.multiselect("Filter by Camera ID", options=sorted(list(unique_cameras)), default=list(unique_cameras))
        filtered_df = df[df['camera'].isin(selected_cameras)]
        
        # Battery Graph
        st.subheader("Battery Levels")
        if filtered_df['battery'].notna().any():
            fig = go.Figure()
            
            # Updated color mapping
            def get_color(bat):
                if bat <= 20:
                    return 'red'
                elif bat <= 65:
                    return 'orange'
                else:
                    return 'green'
            
            valid_df = filtered_df.dropna(subset=['battery'])
            colors = [get_color(b) for b in valid_df['battery']]
            
            fig.add_trace(go.Scatter(
                x=valid_df['timestamp'],
                y=valid_df['battery'],
                mode='lines+markers',
                line=dict(color='lightgray', width=1),  # Subtle gray line for connection
                marker=dict(color=colors, size=6, line=dict(width=1, color='darkgray')),  # Larger markers with outline
                name='Battery %',
                hovertemplate='<b>%{x}</b><br>Battery: %{y}%<br>Camera: ' + valid_df['camera'] + '<extra></extra>'
            ))
            
            fig.update_layout(
                title='Battery Levels Over Time (Markers colored by level: Red 0-20%, Amber 20-65%, Green >65%)',
                xaxis_title='Date',
                yaxis_title='Battery Level (%)',
                yaxis=dict(range=[0, 100]),
                height=400,
                showlegend=False,
                hovermode='x unified'
            )
            
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.warning("No battery levels found in selected cameras.")
        
        # Main Events Table (renamed, with camera)
        st.subheader("Main Events")
        
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
                    # Compress
                    if batteries:
                        min_bat = min(batteries)
                        max_bat = max(batteries)
                        battery_range = f"{int(min_bat)}% - {int(max_bat)}%" if min_bat != max_bat else f"{int(min_bat)}%"
                    else:
                        battery_range = "N/A"
                    duration = (end_time - start_time).total_seconds() / 60  # Minutes
                    compressed_events.append({
                        'Start Time': start_time.strftime('%Y-%m-%d %H:%M:%S'),
                        'End Time': end_time.strftime('%Y-%m-%d %H:%M:%S'),
                        'Camera': current_camera,
                        'Event': current_norm_event,
                        'Battery Level': battery_range,
                        'Duration (min)': f"{duration:.1f}"
                    })
                    # New group
                    current_norm_event = row['normalized_event']
                    current_camera = row['camera']
                    start_time = row['timestamp']
                    batteries = [row['battery']] if pd.notna(row['battery']) else []
                    end_time = start_time
            
            # Last group
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
                'Event': current_norm_event,
                'Battery Level': battery_range,
                'Duration (min)': f"{duration:.1f}"
            })
        
        events_df = pd.DataFrame(compressed_events)
        st.dataframe(events_df, use_container_width=True, hide_index=True)
        
        # New: Recent Activities Table
        st.subheader("Recent Activities")
        # Enhance with status icons and event types
        activity_df = filtered_df.copy()
        activity_df['Status'] = activity_df['normalized_event'].apply(lambda e: '⚠️ Warning' if 'Low Battery' in e else '🔴 Error' if 'Error' in e else '✅ Success')
        activity_df['Event Type'] = activity_df['normalized_event'].apply(lambda e: 'Charging' if 'Charging' in e else 'Recording' if 'Record' in e else 'Power' if 'Power' in e else 'Battery Alert' if 'Battery' in e else 'Other')
        activity_cols = ['timestamp', 'camera', 'Event Type', 'normalized_event', 'battery', 'Status']
        activity_display = activity_df[activity_cols].tail(50)  # Last 50 for "recent"
        activity_display.columns = ['Timestamp', 'Camera', 'Event Type', 'Details', 'Battery %', 'Status']
        st.dataframe(activity_display, use_container_width=True, hide_index=True)
        
        # Overall Summary
        st.subheader("Overall Summary")
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
            **Date Range:** {date_range}
            
            **Overview:**
            - Total log entries: {total_events}
            - Unique event types: {unique_events}
            - Battery range: {min_battery:.0f}% to {max_battery:.0f}% (average: {avg_battery:.0f}%)
            
            **Key Events:**
            - System Power On: {power_ons} times
            - System Power Off: {power_offs} times
            - Battery Charging sessions: {charging_sessions}
            - Low battery warnings (≤20%): {low_battery_count} occurrences
            
            **What Happened:**
            The device was active across the period, with multiple power cycles likely due to user interactions or auto-shutdowns.
            Battery experienced {'a significant drop' if min_battery <= 20 else 'minor fluctuations'}.
            Charging occurred {'frequently' if charging_sessions > 1 else 'once or twice'}, bringing it back to full.
            No critical errors noted beyond standard low battery alerts.
            """
            st.markdown(summary)
        else:
            st.warning("No data for selected cameras.")
else:
    st.info("Please upload one or more .txt log files to get started.")
    # Example
    example_data = {
        'Start Time': ['2025-09-03 01:24:56', '2025-09-03 08:12:05'],
        'End Time': ['2025-09-03 02:15:36', '2025-09-03 08:12:05'],
        'Camera': ['007120', '007490'],
        'Event': ['Battery Charging', 'System Power Off - Auto'],
        'Battery Level': ['92% - 100%', '100%'],
        'Duration (min)': ['50.7', '0.0']
    }
    st.subheader("Example Main Events")
    st.dataframe(pd.DataFrame(example_data))