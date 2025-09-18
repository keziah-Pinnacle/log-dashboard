import streamlit as st
import pandas as pd
from datetime import datetime, timedelta
import plotly.graph_objects as go
import re
from io import BytesIO
import base64
from fpdf import FPDF

# Page config
st.set_page_config(page_title="Log Dashboard", layout="wide")

# Title
st.title("Log Dashboard")

# File uploader
uploaded_files = st.file_uploader("Upload log files (.txt from cameras)", type="txt", accept_multiple_files=True)

if len(uploaded_files) > 0:
    if len(uploaded_files) > 10:
        st.info(f"📁 Uploaded {len(uploaded_files)} files. Each session processes current uploads only.")
    
    # Parse logs
    all_data = []
    unique_cameras = set()
    for uploaded_file in uploaded_files:
        filename = uploaded_file.name
        log_content = uploaded_file.read().decode('utf-8')
        lines = log_content.strip().split('\n')
        
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
                
                normalized_event = full_event.split(' - Battery Level - ')[0].strip() if ' - Battery Level - ' in full_event else full_event
                
                dt = datetime.strptime(timestamp_str, '%Y-%m-%d %H:%M:%S')
                
                battery = None
                if 'Battery Level -' in full_event:
                    battery_str = full_event.split('Battery Level -')[-1].strip().rstrip('%').strip()
                    battery = int(battery_str) if battery_str.isdigit() else None
                
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
        st.error("No valid log entries. Check format.")
    else:
        df = pd.DataFrame(all_data)
        df = df.sort_values('timestamp')
        
        # Time range filter
        col1, col2 = st.columns(2)
        with col1:
            start_date = st.date_input("Start Date", value=df['timestamp'].min().date())
        with col2:
            end_date = st.date_input("End Date", value=df['timestamp'].max().date())
        date_mask = (df['timestamp'].dt.date >= start_date) & (df['timestamp'].dt.date <= end_date)
        filtered_df = df[date_mask]
        
        # Camera filter
        selected_cameras = st.multiselect("Choose Camera ID", options=sorted(list(unique_cameras)), default=list(unique_cameras))
        filtered_df = filtered_df[filtered_df['camera'].isin(selected_cameras)]
        
        # Battery Graph
        st.subheader("Battery Monitoring Timeline")
        if filtered_df['battery'].notna().any():
            fig = go.Figure()
            
            # Filter for valid data
            valid_df = filtered_df.dropna(subset=['battery']).copy()
            if not valid_df.empty:
                # Aggregate duplicates
                valid_df = valid_df.groupby('timestamp').agg({
                    'battery': 'mean',
                    'normalized_event': lambda x: '; '.join(x),
                    'camera': 'first'
                }).reset_index()
                
                # Interpolate gaps >5 min (10-min for speed)
                valid_df['timestamp'] = pd.to_datetime(valid_df['timestamp'])
                valid_df = valid_df.sort_values('timestamp')
                valid_df = valid_df.set_index('timestamp')
                valid_df = valid_df.resample('10T').interpolate(method='linear').reset_index()
                
                # Color function
                def get_color(bat):
                    if bat <= 20:
                        return 'darkred'
                    elif bat <= 60:
                        return 'orange'
                    else:
                        return 'darkgreen'
                
                # Battery level line (single smooth line with nodes)
                fig.add_trace(go.Scatter(
                    x=valid_df['timestamp'],
                    y=valid_df['battery'],
                    mode='lines+markers',
                    line=dict(color='gray', width=2),
                    marker=dict(size=4, color='gray'),
                    name='Battery Level',
                    hovertemplate='<b>Battery</b><br>Time: %{x}<br>Level: %{y}%<extra></extra>'
                ))
                
                # Power On markers (single trace)
                power_on = filtered_df[filtered_df['normalized_event'].str.contains('Power On', na=False)].dropna(subset=['battery'])
                if not power_on.empty:
                    colors = [get_color(b) for b in power_on['battery']]
                    fig.add_trace(go.Scatter(
                        x=power_on['timestamp'],
                        y=power_on['battery'],
                        mode='markers',
                        marker=dict(color=colors, size=8, symbol='triangle-up', line=dict(width=1, color='black')),
                        name='Power On',
                        hovertemplate='<b>Power On</b><br>Time: %{x}<br>Battery: %{y}%<br>Condition: %{customdata}<extra></extra>',
                        customdata=[get_color(b) for b in power_on['battery']]
                    ))
                
                # Power Off markers (single trace)
                power_off = filtered_df[filtered_df['normalized_event'].str.contains('Power Off', na=False)].dropna(subset=['battery'])
                if not power_off.empty:
                    colors = [get_color(b) for b in power_off['battery']]
                    fig.add_trace(go.Scatter(
                        x=power_off['timestamp'],
                        y=power_off['battery'],
                        mode='markers',
                        marker=dict(color='blue', size=8, symbol='triangle-down', line=dict(width=1, color='black')),
                        name='Power Off',
                        hovertemplate='<b>Power Off</b><br>Time: %{x}<br>Battery: %{y}%<extra></extra>'
                    ))
                
                # Charging (single trace, grouped, light black dotted)
                charging_starts = filtered_df[filtered_df['normalized_event'].str.contains('Battery Charging', na=False) & ~filtered_df['normalized_event'].str.contains('Done', na=False)].dropna(subset=['battery'])
                if not charging_starts.empty:
                    charging_groups = []
                    current_group = []
                    for _, row in charging_starts.iterrows():
                        if not current_group or (row['timestamp'] - current_group[-1]['timestamp']).total_seconds() < 300:
                            current_group.append(row)
                        else:
                            charging_groups.append(current_group)
                            current_group = [row]
                    if current_group:
                        charging_groups.append(current_group)
                    
                    for group in charging_groups:
                        start_time = group[0]['timestamp']
                        start_bat = group[0]['battery']
                        end_time = group[-1]['timestamp']
                        end_bat = group[-1]['battery']
                        dur_min = (end_time - start_time).total_seconds() / 60
                        charge_gained = end_bat - start_bat
                        mid_time = start_time + pd.Timedelta(minutes=dur_min/2)
                        fig.add_trace(go.Scatter(
                            x=[start_time, end_time],
                            y=[start_bat, end_bat],
                            mode='lines',
                            line=dict(color='black', width=1, dash='dot'),
                            showlegend=True,
                            name='Charging',
                            hovertemplate='<b>Charging</b><br>Time: %{x}<br>From: {start_bat}% to {end_bat}% in {dur_min:.1f}min (+{charge_gained}%)<extra></extra>'
                        ))
                
                # Recording (single trace per session)
                recording_starts = filtered_df[filtered_df['normalized_event'].str.contains('Start Record', na=False)].dropna(subset=['battery'])
                for start_row in recording_starts.itertuples():
                    start_time = start_row.timestamp
                    start_bat = start_row.battery
                    stop_mask = (filtered_df['timestamp'] > start_time) & (filtered_df['normalized_event'].str.contains('Stop Record', na=False)) & (filtered_df['camera'] == start_row.camera)
                    stop_row = filtered_df.loc[stop_mask].iloc[0] if stop_mask.any() else filtered_df.iloc[-1]
                    end_time = stop_row.timestamp
                    end_bat = stop_row.battery
                    dur_h = (end_time - start_time).total_seconds() / 3600
                    drop = start_bat - end_bat
                    condition = "Healthy" if drop < 5 * dur_h else "Concern"
                    mid_time = start_time + pd.Timedelta(hours=dur_h/2)
                    rec_color = get_color(start_bat)
                    fig.add_hline(y=start_bat, x0=start_time, x1=end_time, line=dict(color=rec_color, width=2, dash='dot'), 
                                  annotation_text=f"Rec {int(start_bat)}% to {int(end_bat)}% over {dur_h:.1f}h ({condition})")
                
                # Usage