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
            
            # Filter for valid data and handle duplicates
            valid_df = filtered_df.dropna(subset=['battery']).copy()
            if not valid_df.empty:
                # Aggregate duplicates
                valid_df = valid_df.groupby('timestamp').agg({
                    'battery': 'mean',
                    'normalized_event': lambda x: '; '.join(x),
                    'camera': 'first'
                }).reset_index()
                
                # Interpolate gaps >5 min
                valid_df['timestamp'] = pd.to_datetime(valid_df['timestamp'])
                valid_df = valid_df.sort_values('timestamp')
                valid_df = valid_df.set_index('timestamp')
                valid_df = valid_df.resample('5T').interpolate(method='linear').reset_index()
                
                # Color function
                def get_color(bat):
                    if bat <= 20:
                        return 'darkred'
                    elif bat <= 60:
                        return 'orange'
                    else:
                        return 'darkgreen'
                
                # Battery level line (smooth)
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
                        line=dict(color=color, width=2),
                        showlegend=False
                    ))
                
                # Power On markers
                power_on = filtered_df[filtered_df['normalized_event'].str.contains('Power On', na=False)].dropna(subset=['battery'])
                if not power_on.empty:
                    colors = [get_color(b) for b in power_on['battery']]
                    fig.add_trace(go.Scatter(
                        x=power_on['timestamp'],
                        y=power_on['battery'],
                        mode='markers',
                        marker=dict(color=colors, size=8, symbol='triangle-up', line=dict(width=1, color='black')),
                        name='Power On',
                        hovertemplate='<b>Power On</b><br>Time: %{x}<br>Battery: %{y}%<extra></extra>'
                    ))
                
                # Power Off markers
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
                
                # Charging segments (separate, docked time/charge gained)
                charging_starts = filtered_df[filtered_df['normalized_event'].str.contains('Battery Charging', na=False) & ~filtered_df['normalized_event'].str.contains('Done', na=False)].dropna(subset=['battery'])
                for start_idx, start_row in charging_starts.iterrows():
                    start_time = start_row['timestamp']
                    start_bat = start_row['battery']
                    # Find end (next non-charging or Done)
                    end_mask = (filtered_df['timestamp'] > start_time) & (~filtered_df['normalized_event'].str.contains('Battery Charging', na=False))
                    end_row = filtered_df.loc[end_mask].iloc[0] if end_mask.any() else filtered_df.iloc[-1]
                    end_time = end_row['timestamp']
                    end_bat = end_row['battery']
                    dur_min = (end_time - start_time).total_seconds() / 60
                    charge_gained = end_bat - start_bat
                    mid_time = start_time + pd.Timedelta(minutes=dur_min/2)
                    fig.add_trace(go.Scatter(
                        x=[start_time, end_time],
                        y=[start_bat, end_bat],
                        mode='lines',
                        line=dict(color='purple', width=2, dash='dot'),
                        showlegend=True,
                        name='Charging'
                    ))
                    fig.add_annotation(x=mid_time, y=(start_bat + end_bat)/2, text=f"Charge {start_bat}% to {end_bat}% in {dur_min:.1f}min (+{charge_gained}%)", 
                                       showarrow=False, font=dict(size=9), bgcolor='white', bordercolor='purple')
                
                # Recording segments (separate, usage/drop)
                recording_starts = filtered_df[filtered_df['normalized_event'].str.contains('Start Record', na=False)].dropna(subset=['battery'])
                for start_row in recording_starts.itertuples():
                    start_time = start_row.timestamp
                    start_bat = start_row.battery
                    # Find next Stop Record
                    stop_mask = (filtered_df['timestamp'] > start_time) & (filtered_df['normalized_event'].str.contains('Stop Record', na=False)) & (filtered_df['camera'] == start_row.camera)
                    stop_row = filtered_df.loc[stop_mask].iloc[0] if stop_mask.any() else filtered_df.iloc[-1]
                    end_time = stop_row.timestamp
                    end_bat = stop_row.battery
                    dur_h = (end_time - start_time).total_seconds() / 3600
                    drop = start_bat - end_bat
                    condition = "Healthy (low drain)" if drop < 5 * dur_h else "Concern (high drain)"
                    mid_time = start_time + pd.Timedelta(hours=dur_h/2)
                    rec_color = get_color(start_bat)
                    fig.add_hline(y=start_bat, x0=start_time, x1=end_time, line=dict(color=rec_color, width=2, dash='dot'), 
                                  annotation_text=f"Rec {start_bat}% to {end_bat}% over {dur_h:.1f}h ({condition})")
                
                # Usage (after DC Remove) - black solid
                usage = filtered_df[filtered_df['normalized_event'].str.contains('DC Remove', na=False)].dropna(subset=['battery'])
                for usage_row in usage.itertuples():
                    start_time = usage_row.timestamp
                    next_mask = filtered_df['timestamp'] > start_time
                    next_row = filtered_df.loc[next_mask].iloc[0] if next_mask.any() else filtered_df.iloc[-1]
                    end_time = next_row.timestamp
                    fig.add_trace(go.Scatter(
                        x=[start_time, end_time],
                        y=[usage_row.battery, next_row.battery],
                        mode='lines',
                        line=dict(color='black', width=2),
                        showlegend=True,
                        name='Usage'
                    ))
                
                # X-axis: Every hour
                fig.update_xaxes(title_text="Time (HH:MM)", tickformat="%H:%M", tick0=filtered_df['timestamp'].min(), dtick="1 hour", tickangle=45)
                
                fig.update_layout(
                    template='plotly_white',  # Clean white
                    title='Battery Monitoring Timeline',
                    yaxis_title='Battery Level (%)',
                    yaxis=dict(range=[0, 100], tickformat='.0f', gridcolor='lightgray'),
                    height=500,
                    font=dict(size=11, family="Arial"),
                    hovermode='x unified',
                    plot_bgcolor='white',
                    paper_bgcolor='white',
                    legend=dict(orientation="h", bgcolor="white", bordercolor="gray"),
                    xaxis=dict(showgrid=True, gridcolor='lightgray', linecolor='gray')
                )
                
                st.plotly_chart(fig, use_container_width=True)
                
                # Export PDF
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
                    
                    pdf.ln(200)
                    pdf.set_font("Arial", size=10)
                    pdf.multi_cell(0, 5, txt=summary)
                    
                    pdf.output(pdf_buffer)
                    pdf_buffer.seek(0)
                    b64 = base64.b64encode(pdf_buffer.read()).decode()
                    href = f'<a href="data:application/pdf;base64,{b64}" download="full_battery_report.pdf">📥 Download Full Report PDF</a>'
                    st.markdown(href, unsafe_allow_html=True)
        else:
            st.warning("No battery data in range.")
        
        # Activity Timeline (narrative summary)
        st.subheader("Log Summary")
        if not filtered_df.empty:
            narrative = generate_narrative(filtered_df)
            st.markdown(narrative)
else:
    st.info("Upload .txt log files to start.")

def generate_narrative(filtered_df):
    narrative = "Summary of camera activity:\n\n"
    power_on = filtered_df[filtered_df['normalized_event'].str.contains('Power On', na=False)].dropna(subset=['battery'])
    if not power_on.empty:
        narrative += f"The camera powered on {len(power_on)} times, starting with battery levels from {int(power_on['battery'].min())}% to {int(power_on['battery'].max())}% (Good condition if >60%, caution 20-60%, critical <20%).\n"
    
    recording_starts = filtered_df[filtered_df['normalized_event'].str.contains('Start Record', na=False)].dropna(subset=['battery'])
    if not recording_starts.empty:
        for start_row in recording_starts.itertuples():
            start_time = start_row.timestamp.strftime('%H:%M')
            start_bat = int(start_row.battery)
            condition = "Good" if start_bat > 60 else "Caution" if start_bat > 20 else "Critical"
            narrative += f"Recording started at {start_time} with {start_bat}% battery ({condition}).\n"
    
    charging = filtered_df[filtered_df['normalized_event'].str.contains('Battery Charging', na=False)].dropna(subset=['battery'])
    if not charging.empty:
        narrative += f"Charging occurred {len(charging)} times, starting from as low as {int(charging['battery'].min())}%.\n"
    
    low_events = filtered_df[filtered_df['battery'] <= 20]
    if not low_events.empty:
        narrative += f"Critical low battery detected {len(low_events)} times—recommend check.\n"
    
    total_runtime = (filtered_df['timestamp'].max() - filtered_df['timestamp'].min()).total_seconds() / 3600
    narrative += f"Total runtime: {total_runtime:.1f} hours. Overall battery health: {'Good' if filtered_df['battery'].min() > 20 else 'Needs attention'}."
    return narrative