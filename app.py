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
        st.subheader("Battery & Events Timeline")
        if filtered_df['battery'].notna().any():
            fig = go.Figure()
            
            # Filter for valid data and handle duplicates for smoothing
            valid_df = filtered_df.dropna(subset=['battery']).copy()
            if not valid_df.empty:
                # Aggregate duplicates: average battery, concatenate events
                valid_df = valid_df.groupby('timestamp').agg({
                    'battery': 'mean',
                    'normalized_event': lambda x: '; '.join(x),
                    'camera': 'first'
                }).reset_index()
                
                # Interpolate only large gaps (>5 min) for smoothness without overdoing
                valid_df['timestamp'] = pd.to_datetime(valid_df['timestamp'])
                valid_df = valid_df.sort_values('timestamp')
                valid_df = valid_df.set_index('timestamp')
                valid_df = valid_df.resample('5T').interpolate(method='linear').reset_index()  # 5-min intervals for gaps
                
                # Color function
                def get_color(bat):
                    if bat <= 20:
                        return 'darkred'
                    elif bat <= 60:
                        return 'orange'
                    else:
                        return 'darkgreen'
                
                # Battery level line (colored segments, smooth)
                for i in range(1, len(valid_df)):
                    start_bat = valid_df.iloc[i-1]['battery']
                    end_bat = valid_df.iloc[i]['battery']
                    start_time = valid_df.iloc[i-1]['timestamp']
                    end_time = valid_df.iloc[i]['timestamp']
                    color = get_color((start_bat + end_bat) / 2)
                    fig.add_trace(go.Scatter(
                        x=[start_time, end_time],
                        y=[start_bat, end_bat],
                        mode='lines',
                        line=dict(color=color, width=3),
                        showlegend=False,
                        name=f'Battery {color}'
                    ))
                
                # Power On markers with labels
                power_on = filtered_df[filtered_df['normalized_event'].str.contains('Power On', na=False)].dropna(subset=['battery'])
                if not power_on.empty:
                    colors = [get_color(b) for b in power_on['battery']]
                    fig.add_trace(go.Scatter(
                        x=power_on['timestamp'],
                        y=power_on['battery'],
                        mode='markers+text',
                        marker=dict(color=colors, size=12, symbol='triangle-up', line=dict(width=2, color='black')),
                        text=[f"Power On {int(b)}%" for b in power_on['battery']],
                        textposition="top center",
                        textfont=dict(size=10),
                        name='Power On',
                        hovertemplate='<b>Power On</b><br>Time: %{x}<br>Battery: %{y}%<extra></extra>'
                    ))
                
                # Recording horizontal lines with duration labels
                recording_starts = filtered_df[filtered_df['normalized_event'].str.contains('Start Record', na=False)].dropna(subset=['battery'])
                for start_row in recording_starts.itertuples():
                    start_time = start_row.timestamp
                    start_bat = start_row.battery
                    # Find next Stop Record for same camera
                    stop_mask = (filtered_df['timestamp'] > start_time) & (filtered_df['normalized_event'].str.contains('Stop Record', na=False)) & (filtered_df['camera'] == start_row.camera)
                    stop_row = filtered_df.loc[stop_mask].iloc[0] if stop_mask.any() else filtered_df.iloc[-1]
                    end_time = stop_row.timestamp
                    end_bat = stop_row.battery
                    duration = (end_time - start_time).total_seconds() / 3600  # Hours
                    fig.add_hline(y=start_bat, x0=start_time, x1=end_time, line=dict(color='blue', width=4, dash='dash'), 
                                  annotation_text=f'Recording {duration:.1f}h at {int(start_bat)}%')
                
                # Charging segments with duration
                charging = filtered_df[filtered_df['normalized_event'].str.contains('Battery Charging', na=False)].dropna(subset=['battery'])
                if not charging.empty:
                    for i in range(1, len(charging)):
                        start_time = charging.iloc[i-1]['timestamp']
                        end_time = charging.iloc[i]['timestamp']
                        avg_bat = (charging.iloc[i-1]['battery'] + charging.iloc[i]['battery']) / 2
                        dur_min = (end_time - start_time).total_seconds() / 60
                        fig.add_trace(go.Scatter(
                            x=[start_time, end_time],
                            y=[charging.iloc[i-1]['battery'], charging.iloc[i]['battery']],
                            mode='lines',
                            line=dict(color='purple', width=4, dash='dot'),
                            showlegend=False,
                            name='Charging'
                        ))
                        fig.add_annotation(x= (start_time + end_time)/2, y=avg_bat, text=f'Charge {dur_min:.1f}min', showarrow=False)
                
                # Usage (after DC Remove) - black line
                usage = filtered_df[filtered_df['normalized_event'].str.contains('DC Remove', na=False)].dropna(subset=['battery'])
                for usage_row in usage.itertuples():
                    start_time = usage_row.timestamp
                    # Next event or end
                    next_mask = filtered_df['timestamp'] > start_time
                    next_row = filtered_df.loc[next_mask].iloc[0] if next_mask.any() else filtered_df.iloc[-1]
                    end_time = next_row.timestamp
                    fig.add_trace(go.Scatter(
                        x=[start_time, end_time],
                        y=[usage_row.battery, next_row.battery],
                        mode='lines',
                        line=dict(color='black', width=3),
                        showlegend=True,
                        name='Usage (Drain)'
                    ))
                
                # X-axis: Time if <1 day, Date otherwise
                range_days = (filtered_df['timestamp'].max() - filtered_df['timestamp'].min()).days
                if range_days < 1:
                    fig.update_xaxes(title_text="Time (HH:MM)", tickformat="%H:%M")
                else:
                    fig.update_xaxes(title_text="Date", tickformat="%b %d")
                
                fig.update_layout(
                    title='Battery & Events Timeline (Smooth, No Skipped Days)',
                    yaxis_title='Battery Level (%)',
                    yaxis=dict(range=[0, 100], tickformat='.0f'),
                    height=500,
                    font=dict(size=12, family="Arial Black"),
                    hovermode='x unified',
                    plot_bgcolor='lightgray',
                    legend=dict(orientation="h", bgcolor="white", bordercolor="black"),
                    xaxis=dict(showgrid=True, gridcolor='gray')
                )
                
                st.plotly_chart(fig, use_container_width=True)
                
                # Export PDF with summary
                if st.button("📄 Export Full Report as PDF"):
                    pdf_buffer = BytesIO()
                    pdf = FPDF()
                    pdf.add_page()
                    pdf.set_font("Arial", size=16)
                    pdf.cell(0, 10, txt="Battery Report", ln=True, align='C')
                    pdf.set_font("Arial", size=12)
                    pdf.cell(0, 10, txt=f"Date Range: {start_date} to {end_date}", ln=True)
                    pdf.cell(0, 10, txt=f"Camera: {', '.join(selected_cameras)}", ln=True)
                    
                    # Add graph as PNG
                    graph_buffer = BytesIO()
                    fig.write_image(graph_buffer, format='png', engine='kaleido')
                    graph_buffer.seek(0)
                    pdf.image(graph_buffer, x=10, y=30, w=190)
                    
                    # Add summary text
                    pdf.ln(200)
                    pdf.set_font("Arial", size=10)
                    power_on_df = filtered_df[filtered_df['normalized_event'].str.contains('Power On', na=False)]
                    recording_start_df = filtered_df[filtered_df['normalized_event'].str.contains('Start Record', na=False)]
                    charging_df = filtered_df[filtered_df['normalized_event'].str.contains('Battery Charging', na=False)]
                    low_events = filtered_df[filtered_df['battery'] <= 20]
                    
                    summary = f"Battery Usage:\n"
                    if not power_on_df.empty:
                        summary += f"- Powered on {len(power_on_df)} times (battery {int(power_on_df['battery'].min())}%-{int(power_on_df['battery'].max())}%).\n"
                    if not recording_start_df.empty:
                        summary += f"- Recorded {len(recording_start_df)} sessions (battery {int(recording_start_df['battery'].min())}%-{int(recording_start_df['battery'].max())}%).\n"
                    if not charging_df.empty:
                        summary += f"- Charged {len(charging_df)} times (from {int(charging_df['battery'].min())}%).\n"
                    if not low_events.empty:
                        summary += f"- Low battery alerts: {len(low_events)} (quick drops may indicate battery health issue).\n"
                    summary += f"Total events: {len(filtered_df)}."
                    
                    pdf.multi_cell(0, 5, txt=summary)
                    
                    pdf.output(pdf_buffer)
                    pdf_buffer.seek(0)
                    b64 = base64.b64encode(pdf_buffer.read()).decode()
                    href = f'<a href="data:application/pdf;base64,{b64}" download="full_battery_report.pdf">📥 Download Full Report PDF</a>'
                    st.markdown(href, unsafe_allow_html=True)
        else:
            st.warning("No battery data in range.")
        
        # Activity Timeline (fixed error)
        st.subheader("Activity Timeline")
        if not filtered_df.empty:
            narrative = []
            prev_battery = None
            prev_time = None
            for _, row in filtered_df.iterrows():
                if pd.notna(row['battery']):
                    bat_status = "Low" if row['battery'] <= 20 else "Medium" if row['battery'] <= 60 else "Good"
                    event_desc = {
                        'System Power On': f"Powered on at {int(row['battery'])}% ({bat_status})",
                        'Start Record': f"Started recording at {int(row['battery'])}% ({bat_status})",
                        'Stop Record': f"Stopped recording at {int(row['battery'])}% ({bat_status})",
                        'Battery Charging': f"Charging at {int(row['battery'])}%",
                        'DC Remove': f"Disconnected from dock at {int(row['battery'])}%—started usage",
                        'Low Battery': f"Low battery alert at {int(row['battery'])}%"
                    }.get(row['normalized_event'], row['normalized_event'])
                    
                    if prev_time:
                        dur_min = (row['timestamp'] - prev_time).total_seconds() / 60
                        if dur_min > 5:  # Significant gap
                            narrative.append(f"At {row['timestamp'].strftime('%H:%M:%S')}, {event_desc}. (Previous: {dur_min:.1f} min ago)")
                        else:
                            narrative.append(f"At {row['timestamp'].strftime('%H:%M:%S')}, {event_desc}.")
                    else:
                        narrative.append(f"At {row['timestamp'].strftime('%H:%M:%S')}, {event_desc}.")
                    
                    # Check for quick drops (fixed: use prev_battery)
                    if prev_battery is not None and row['battery'] < prev_battery - 5:
                        narrative.append(f"  → Quick battery drop detected (from {int(prev_battery)}% to {int(row['battery'])}%)—possible health issue.")
                    
                    prev_battery = row['battery']
                    prev_time = row['timestamp']
            
            # Recording/Charging durations
            recording_dur = filtered_df[filtered_df['normalized_event'].str.contains('Stop Record', na=False)]['battery'].count() * 1.0  # Approx hours
            charging_dur = filtered_df[filtered_df['normalized_event'].str.contains('Battery Changing Done', na=False)]['battery'].count() * 0.5  # Approx hours
            narrative.append(f"\nTotal recording time: ~{recording_dur:.1f} hours. Charging time: ~{charging_dur:.1f} hours.")
            
            st.markdown("\n".join(narrative))
else:
    st.info("Upload .txt log files to start.")