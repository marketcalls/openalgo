# OpenAlgo Installation Guide

## Prerequisites

Before installing OpenAlgo, ensure you have the following prerequisites installed:

- **Visual Studio Code (VS Code)** installed on Windows.
- **Python** version 3.10 or 3.11 installed.
- **Git** for cloning the repository (Download from [https://git-scm.com/downloads](https://git-scm.com/downloads)).
- **Node.js** for CSS compilation (Download from [https://nodejs.org/](https://nodejs.org/)).

## Installation Steps

1. **Install VS Code Extensions**: 
   - Open VS Code
   - Navigate to the Extensions section on the left tab
   - Install the Python, Pylance, and Jupyter extensions

2. **Clone the Repository**: 
   Open the VS Code Terminal and clone the OpenAlgo repository:
   ```bash
   git clone https://github.com/marketcalls/openalgo
   ```

3. **Install Python Dependencies**: 

   For Windows users:
   ```bash
   """
Trading Journal Application - Main Application
--------------------------------------------
This is the main Dash application file that defines the layout and callbacks
for the trading journal application.
"""

import dash
from dash import dcc, html, dash_table, callback, Input, Output, State, no_update
import dash_bootstrap_components as dbc
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import base64
import io
import json
from io import StringIO
import plotly.io as pio
# import os # Removed as no longer directly used for path joining here
from datetime import datetime

# Import utility modules
# Updated data_loader import
from app.utils.data_loader import load_trade_csv, preprocess_data, load_data_csv, save_data_csv
from app.utils import metrics_calculator, advanced_metrics, advanced_dashboard, global_filters, journal_management, calendar_view # Removed data_loader from here
from app.utils import wmy_analysis # ADD THIS IMPORT

# Initialize the Dash app with Bootstrap theme and Font Awesome icons
app = dash.Dash(
    __name__, 
    external_stylesheets=[dbc.themes.DARKLY, dbc.icons.FONT_AWESOME],  # Use a dark theme
    suppress_callback_exceptions=True
)
pio.templates.default = "plotly_dark"

# Content for Overview section
overview_section_content = html.Div([
    dbc.Card([
        dbc.CardHeader(html.H4("Overall Performance Metrics", className="card-title")), # Use H4 for card titles
        dbc.CardBody([
            html.Div(id='overall-metrics-display')
        ])
    ], className="mb-4"),
    dbc.Row([
        dbc.Col(dbc.Card([
            dbc.CardHeader(html.H4("Equity Curve", className="card-title")),
            dbc.CardBody([
                dcc.Graph(id='overall-equity-curve', style={'height': '400px', 'width': '100%'})
            ])
        ], className="mb-4"), width=12, lg=6),
        dbc.Col(dbc.Card([
            dbc.CardHeader(html.H4("P&L Distribution", className="card-title")),
            dbc.CardBody([
                dcc.Graph(id='pnl-distribution-histogram', style={'height': '400px', 'width': '100%'})
            ])
        ], className="mb-4"), width=12, lg=6)
    ]),
    dbc.Card([
        dbc.CardHeader(html.H4("P&L by Period", className="card-title")),
        dbc.CardBody([
            dbc.Row([
                dbc.Col([
                    dcc.RadioItems(
                        id='pnl-period-selector',
                        options=[
                            {'label': 'Daily', 'value': 'D'},
                            {'label': 'Weekly', 'value': 'W'},
                            {'label': 'Monthly', 'value': 'M'}
                        ],
                        value='D',
                        inline=True,
                        className="mb-2"
                    )
                ])
            ]),
            dcc.Graph(id='pnl-by-period-chart', style={'height': '400px', 'width': '100%'})
        ])
    ], className="mb-4"),
])

# Content for Algorithm Analysis section
algo_analysis_section_content = html.Div([
    dbc.Card([
        dbc.CardHeader(html.H4("Algorithm Selection & Metrics", className="card-title")),
        dbc.CardBody([
            dcc.Dropdown(
                id='algorithm-selector',
                placeholder="Select Algorithm ID",
                className="mb-3"
            ),
            html.Div(id='algo-metrics-display')
        ])
    ], className="mb-4"),
    dbc.Card([
        dbc.CardHeader(html.H4("Algorithm Equity Curve", className="card-title")),
        dbc.CardBody([
            dcc.Graph(id='algo-equity-curve', style={'height': '400px', 'width': '100%'})
        ])
    ], className="mb-4"),
])

# Content for Advanced Analytics section
advanced_analytics_section_content = html.Div([
    dbc.Card([
        dbc.CardHeader(html.H4("Advanced Analytics", className="card-title")),
        dbc.CardBody([
            advanced_dashboard.create_advanced_metrics_layout()
        ])
    ], className="mb-4"),
])

# Content for Trade Details section
trade_details_section_content = html.Div([
    dbc.Card([
        dbc.CardHeader(html.H4("Trade Details", className="card-title")),
        dbc.CardBody([
            dash_table.DataTable(
                id='basic-trade-table',
                page_size=10,
                style_table={'overflowX': 'auto', 'minWidth': '100%'},
                style_cell={
                    'height': 'auto',
                    'minWidth': '80px', 'width': '100px', 'maxWidth': '180px',
                    'whiteSpace': 'normal'
                },
                style_header={
                    'backgroundColor': 'rgb(230, 230, 230)',
                    'fontWeight': 'bold'
                },
                style_data_conditional=[
                    {
                        'if': {'row_index': 'odd'},
                        'backgroundColor': 'rgb(248, 248, 248)'
                    }
                ]
            )
        ])
    ], className="mb-4"),
])

# Content for Journal Management section
journal_management_section_content = html.Div([
    dbc.Card([
        dbc.CardHeader(html.H4("Journal Management", className="card-title")),
        dbc.CardBody([
            journal_management.create_journal_entry_layout()
        ])
    ], className="mb-4"),
])

# Helper function for initial data load (REMOVED)
# def get_initial_trade_data():
#     master_df = load_data_csv()
#     if master_df is not None and not master_df.empty:
#         return master_df.to_json(date_format='iso', orient='split')
#     return None

# Define the app layout
app.layout = dbc.Container(id='app-container', children=[
    dcc.Location(id='url', refresh=False),

    # Data Stores (can remain at the top level)
    dcc.Store(id='trade-data-store'), # Removed data=get_initial_trade_data()
    dcc.Store(id='filtered-data-store'),
    dcc.Store(id='sidebar-state-store', data=0), # 0 for 'CLOSED', 1 for 'NARROW', etc.
    dcc.Store(id='stored-pnl-range'), 

    # Sidebar (now a direct child of app-container, after stores/location)
    html.Div([ 
        dbc.Row([
            dbc.Col(html.H4("Navigation", className="mb-0 mt-1"), width='auto'), # Adjusted H4 margin
            dbc.Col(
                dbc.Button(html.I(className="fas fa-bars"), id="sidebar-toggle-button", n_clicks=0, className="ms-auto border-0", style={'backgroundColor': 'transparent', 'fontSize': '1.5rem'}), 
                width='auto', className="d-flex justify-content-end"
            )
        ], align="center", className="mb-2"), # New row for title and button
        html.Hr(className="mt-1 mb-3"), # Adjusted Hr margin
                dbc.Nav([
                    dbc.NavLink([html.I(className="fas fa-home me-2"), "Overview"], href="/overview", active="exact", id="nav-overview"),
                    dbc.NavLink([html.I(className="fas fa-cogs me-2"), "Algorithm Analysis"], href="/algo-analysis", active="exact", id="nav-algo-analysis"),
                    dbc.NavLink([html.I(className="fas fa-chart-pie me-2"), "Advanced Analytics"], href="/advanced-analytics", active="exact", id="nav-advanced-analytics"),
                    dbc.NavLink([html.I(className="fas fa-table me-2"), "Trade Details"], href="/trade-details", active="exact", id="nav-trade-details"),
                    dbc.NavLink([html.I(className="fas fa-book me-2"), "Journal Management"], href="/journal-management", active="exact", id="nav-journal-management"),
                    dbc.NavLink([html.I(className="fas fa-calendar-alt me-2"), "Calendar View"], href="/calendar-view", active="exact", id="nav-calendar-view"),
                    dbc.NavLink([html.I(className="fas fa-calendar-week me-2"), "WMY Analysis"], href="/wmy-analysis", active="exact", id="nav-wmy-analysis"), # ADDED THIS LINE
                ],
                vertical=True,
                pills=True,
                id="sidebar-nav"
                ),
                html.Hr(className="mt-3"), # Ensure some space, added mt-3
                dbc.Accordion([
                    dbc.AccordionItem(
                        global_filters.create_global_filters_layout(), # This now returns a Card without its own Header
                        title="Global Filters", # This is the main clickable title for filters
                        item_id="global-filters-accordion"
                    )
                ], start_collapsed=True, flush=True, id="sidebar-accordion-filters", className="mt-3") # Added mt-3
            ],
            id="sidebar",
            className="sidebar-active p-3", # Initial classes for active sidebar
        ), # End of sidebar Div

    # Page Content Wrapper (now a direct child of app-container, after sidebar)
    html.Div([ 
        # Header Row with Toggle Button and Title
        dbc.Row([
            dbc.Col(
                html.H1("Algorithmic Trading Dashboard", className="my-4"),
                width=True 
            )
        ], align="center", className="mb-4 header-row"),

        # File Upload Section
                dbc.Row([
                    dbc.Col([
                        dcc.Upload(
                            id='upload-data',
                            children=html.Div(['Drag and Drop or ', html.A('Select Trade CSV')]),
                            style={
                                'width': '100%', 'height': '60px', 'lineHeight': '60px',
                                'borderWidth': '1px', 'borderStyle': 'dashed',
                                'borderRadius': '5px', 'textAlign': 'center', 'margin': '10px 0 20px 0'
                            },
                            multiple=False
                        ),
                        html.Div(id='upload-status')
                    ])
                ]),
                # Wrapper for dynamic content, visibility controlled by data upload
                html.Div(
                    id='dynamic-content-area',
                    style={'display': 'none'}, 
                    children=[
                        html.Div(id='page-content') 
                    ]
                )
            ],
            id="page-content-wrapper",
            className="content-shifted", # Initial class for shifted content
    ), # End of page-content-wrapper Div

    # Modal for daily trades view from Calendar
    dbc.Modal([
        dbc.ModalHeader(dbc.ModalTitle(id='daily-trades-modal-title')), # Title can be dynamic
        dbc.ModalBody(html.Div(id='daily-trades-content')), # Content will be a DataTable
        dbc.ModalFooter(dbc.Button("Close", id="close-daily-trades-modal", className="ms-auto", n_clicks=0))
    ], id='daily-trades-modal', size="xl", is_open=False), # Large modal, initially closed
    
    # P&L Range Modal
    dbc.Modal([
        dbc.ModalHeader(dbc.ModalTitle("Select P&L Range")),
        dbc.ModalBody([
            dcc.RangeSlider(
                id='modal-pnl-range-slider',
                min=-1000, # Placeholder, will be updated by callback
                max=1000,  # Placeholder
                step=100,  # Placeholder
                # marks={i: f'${i}' for i in range(-1000, 1001, 200)}, # Placeholder
                value=[-1000, 1000], # Placeholder
                tooltip={'placement': 'bottom', 'always_visible': True},
            ),
            html.Div(id='modal-pnl-slider-container-helper', style={'padding': '10px 0'}) 
        ]),
        dbc.ModalFooter([
            dbc.Button("Cancel", id="cancel-pnl-range-button", color="secondary", outline=True),
            dbc.Button("Apply", id="apply-pnl-range-button", color="primary", className="ms-2")
        ])
    ], id='pnl-range-modal', is_open=False, size="lg", centered=True),

], fluid=True)


# Callback for file upload
@callback(
    Output('trade-data-store', 'data', allow_duplicate=True),
    Output('upload-status', 'children'),
    Input('upload-data', 'contents'),
    State('upload-data', 'filename'),
    prevent_initial_call=True
)
def update_output(contents, filename):
    if contents is None:
        return no_update, None
    
    try:
        content_type, content_string = contents.split(',')
        decoded = base64.b64decode(content_string).decode('utf-8')
        
        df = load_trade_csv(decoded)
        processed_df = preprocess_data(df)

        processed_df['Trade type'] = "Algo"
        processed_df['AddedTimestamp'] = pd.to_datetime(datetime.now())

        existing_df = load_data_csv()

        combined_df = pd.concat([existing_df, processed_df], ignore_index=True)
        combined_df['AddedTimestamp'] = pd.to_datetime(combined_df['AddedTimestamp'], errors='coerce')
        combined_df = combined_df.sort_values(by='AddedTimestamp', ascending=False, na_position='last')
        final_df = combined_df.drop_duplicates(subset=['TradeID'], keep='first')

        save_data_csv(final_df)

        if final_df is not None and not final_df.empty:
            updated_store_data = final_df.to_json(date_format='iso', orient='split')
        else:
            updated_store_data = None
        
        message = dbc.Alert(
            f"Successfully loaded and processed {filename}. All data refreshed.",
            color="success"
        )
        
        return updated_store_data, message
        
    except Exception as e:
        message = dbc.Alert(
            f"Error processing file: {str(e)}",
            color="danger"
        )
        return no_update, message


# Callback for initial data load
@app.callback(
    Output('trade-data-store', 'data', allow_duplicate=True),
    Input('url', 'pathname'),
    prevent_initial_call='initial_duplicate' # THIS IS THE LINE TO ENSURE IS CORRECT
)
def load_initial_data(pathname):
    master_df = load_data_csv()
    if master_df is not None and not master_df.empty:
        return master_df.to_json(date_format='iso', orient='split')
    return None


# New callback to toggle dynamic content visibility based on trade-data-store
@app.callback(
    Output('dynamic-content-area', 'style'),
    Input('trade-data-store', 'data')
)
def toggle_dynamic_content_visibility(trade_data_json):
    if trade_data_json is not None:
        try:
            df = pd.read_json(io.StringIO(trade_data_json), orient='split')
            if not df.empty:
                return {'display': 'block'}
        except ValueError:
            pass
    return {'display': 'none'}

# datetime is still used for AddedTimestamp. pandas (pd) and io.StringIO are used.

# Callback for overall metrics display
# Callback for overall metrics display
@callback(
    Output('overall-metrics-display', 'children'),
    Output('overall-equity-curve', 'figure'),
    Output('pnl-distribution-histogram', 'figure'),
    Input('filtered-data-store', 'data'),
    State('trade-data-store', 'data'),
    Input('url', 'pathname')
)
def update_overall_metrics(filtered_json_data, raw_json_data, pathname):
    if pathname != '/overview':
        empty_fig = go.Figure()
        empty_fig.update_layout(
            title="No data available",
            xaxis=dict(showgrid=False, zeroline=False, showticklabels=False),
            yaxis=dict(showgrid=False, zeroline=False, showticklabels=False)
        )
        return None, empty_fig, empty_fig

    json_data_to_use = filtered_json_data
    if json_data_to_use is None:
        json_data_to_use = raw_json_data
    
    if json_data_to_use is None:
        empty_fig = go.Figure()
        empty_fig.update_layout(
            title="No data available",
            xaxis=dict(showgrid=False, zeroline=False, showticklabels=False),
            yaxis=dict(showgrid=False, zeroline=False, showticklabels=False)
        )
        return None, empty_fig, empty_fig
    
    df = pd.read_json(StringIO(json_data_to_use), orient='split')
    
    stats = metrics_calculator.calculate_summary_stats(df)
    
    df_with_cum_pnl = metrics_calculator.calculate_cumulative_pnl(df)
    
    metrics_cards = dbc.Row([
        dbc.Col(dbc.Card([
            dbc.CardHeader("Total P&L"),
            dbc.CardBody(html.H4(f"${stats['total_pnl']:.2f}"))
        ]), width=12, sm=6, md=4, lg=3, className="mb-3"),
        dbc.Col(dbc.Card([
            dbc.CardHeader("Total Trades"),
            dbc.CardBody(html.H4(f"{stats['total_trades']}"))
        ]), width=12, sm=6, md=4, lg=3, className="mb-3"),
        dbc.Col(dbc.Card([
            dbc.CardHeader("Win Rate"),
            dbc.CardBody(html.H4(f"{stats['win_rate']:.2%}"))
        ]), width=12, sm=6, md=4, lg=3, className="mb-3"),
        dbc.Col(dbc.Card([
            dbc.CardHeader("Profit Factor"),
            dbc.CardBody(html.H4(f"{stats['profit_factor']:.2f}"))
        ]), width=12, sm=6, md=4, lg=3, className="mb-3")
    ])
    
    equity_fig = px.line(
        df_with_cum_pnl, 
        x='OpenTimestamp', 
        y='CumulativeP&L',
        title='Equity Curve'
    )
    equity_fig.update_layout(
        xaxis_title="Date",
        yaxis_title="Cumulative P&L ($)",
        hovermode="x unified"
    )
    
    hist_fig = px.histogram(
        df, 
        x='NetP&L',
        nbins=30,
        title='P&L Distribution'
    )
    hist_fig.update_layout(
        xaxis_title="Net P&L ($)",
        yaxis_title="Number of Trades",
        bargap=0.1
    )
    
    if 'AlgorithmID' in df.columns:
        algo_options = [{'label': algo, 'value': algo} for algo in sorted(df['AlgorithmID'].unique())]
    else:
        algo_options = []
    
    return metrics_cards, equity_fig, hist_fig


# Callback for P&L by period chart
@app.callback(
    Output('pnl-by-period-chart', 'figure'),
    Input('filtered-data-store', 'data'),
    State('trade-data-store', 'data'),
    Input('pnl-period-selector', 'value')
)
def update_pnl_by_period(filtered_json_data, raw_json_data, period):
    json_data_to_use = filtered_json_data
    if json_data_to_use is None:
        json_data_to_use = raw_json_data
    
    if json_data_to_use is None:
        empty_fig = go.Figure()
        empty_fig.update_layout(
            title="No data available",
            xaxis=dict(showgrid=False, zeroline=False, showticklabels=False),
            yaxis=dict(showgrid=False, zeroline=False, showticklabels=False)
        )
        return empty_fig
    
    df = pd.read_json(StringIO(json_data_to_use), orient='split')

    if 'OpenTimestamp' in df.columns:
        df['OpenTimestamp'] = pd.to_datetime(df['OpenTimestamp'], errors='coerce')
    else:
        empty_fig = go.Figure()
        empty_fig.update_layout(title="'OpenTimestamp' column missing in data")
        return empty_fig
            
    period_label = "Daily" if period == 'D' else "Weekly" if period == 'W' else "Monthly"
    
    df['Period'] = df['OpenTimestamp'].dt.to_period(period)
    period_pnl = df.groupby('Period')['NetP&L'].sum().reset_index()
    period_pnl['Period'] = period_pnl['Period'].astype(str)
    
    fig = px.bar(
        period_pnl,
        x='Period',
        y='NetP&L',
        title=f'{period_label} P&L',
        color='NetP&L',
        color_continuous_scale=['red', 'green'],
        color_continuous_midpoint=0
    )
    
    fig.update_layout(
        xaxis_title=f"{period_label} Period",
        yaxis_title="Net P&L ($)",
        coloraxis_showscale=False
    )
    
    return fig


# Callback to populate algorithm selector options
@app.callback(
    Output('algorithm-selector', 'options'),
    Input('filtered-data-store', 'data'),
    State('trade-data-store', 'data'),
    Input('url', 'pathname')
)
def set_algorithm_options(filtered_json_data, raw_json_data, pathname):
    if pathname != '/algo-analysis':
        return []

    json_data_to_use = filtered_json_data
    if json_data_to_use is None:
        json_data_to_use = raw_json_data
    
    if json_data_to_use is None:
        return []
    
    try:
        df = pd.read_json(StringIO(json_data_to_use), orient='split')
        if 'AlgorithmID' in df.columns:
            algo_options = [{'label': algo, 'value': algo} for algo in sorted(df['AlgorithmID'].unique())]
            return algo_options
        else:
            return []
    except Exception as e:
        print(f"Error setting algorithm options: {e}")
        return []


# Callback for algorithm-specific analysis
@app.callback(
    Output('algo-metrics-display', 'children'),
    Output('algo-equity-curve', 'figure'),
    Input('filtered-data-store', 'data'),
    State('trade-data-store', 'data'),
    Input('algorithm-selector', 'value'),
    prevent_initial_call=True
)
def update_algorithm_analysis(filtered_json_data, raw_json_data, selected_algo):
    json_data_to_use = filtered_json_data
    if json_data_to_use is None:
        json_data_to_use = raw_json_data

    if json_data_to_use is None or selected_algo is None:
        empty_fig = go.Figure()
        empty_fig.update_layout(
            title="No algorithm selected",
            xaxis=dict(showgrid=False, zeroline=False, showticklabels=False),
            yaxis=dict(showgrid=False, zeroline=False, showticklabels=False)
        )
        return None, empty_fig
    
    df = pd.read_json(StringIO(json_data_to_use), orient='split')

    if 'OpenTimestamp' in df.columns:
        df['OpenTimestamp'] = pd.to_datetime(df['OpenTimestamp'], errors='coerce')
    if 'CloseTimestamp' in df.columns:
        df['CloseTimestamp'] = pd.to_datetime(df['CloseTimestamp'], errors='coerce')
    
    algo_df = df[df['AlgorithmID'] == selected_algo]
    
    if algo_df.empty:
        empty_fig = go.Figure()
        empty_fig.update_layout(title="No data for selected algorithm")
        return None, empty_fig
    
    stats = metrics_calculator.calculate_summary_stats(algo_df)
    
    algo_df_with_cum_pnl = metrics_calculator.calculate_cumulative_pnl(algo_df)
    
    metrics_cards = dbc.Row([
        dbc.Col(dbc.Card([
            dbc.CardHeader("Algorithm P&L"),
            dbc.CardBody(html.H4(f"${stats['total_pnl']:.2f}"))
        ]), width=12, sm=6, md=4, lg=3, className="mb-3"),
        dbc.Col(dbc.Card([
            dbc.CardHeader("Algorithm Trades"),
            dbc.CardBody(html.H4(f"{stats['total_trades']}"))
        ]), width=12, sm=6, md=4, lg=3, className="mb-3"),
        dbc.Col(dbc.Card([
            dbc.CardHeader("Algorithm Win Rate"),
            dbc.CardBody(html.H4(f"{stats['win_rate']:.2%}"))
        ]), width=12, sm=6, md=4, lg=3, className="mb-3"),
        dbc.Col(dbc.Card([
            dbc.CardHeader("Algorithm Profit Factor"),
            dbc.CardBody(html.H4(f"{stats['profit_factor']:.2f}"))
        ]), width=12, sm=6, md=4, lg=3, className="mb-3")
    ])
    
    equity_fig = px.line(
        algo_df_with_cum_pnl, 
        x='OpenTimestamp', 
        y='CumulativeP&L',
        title=f'Algorithm {selected_algo} Equity Curve'
    )
    equity_fig.update_layout(
        xaxis_title="Date",
        yaxis_title="Cumulative P&L ($)",
        hovermode="x unified"
    )
    
    return metrics_cards, equity_fig




# Callback for trade table
@app.callback(
    Output('basic-trade-table', 'data'),
    Output('basic-trade-table', 'columns'),
    Output('basic-trade-table', 'style_header'),
    Output('basic-trade-table', 'style_cell'),
    Output('basic-trade-table', 'style_data_conditional'),
    Input('filtered-data-store', 'data'),
    State('trade-data-store', 'data')
)
def update_trade_table(filtered_json_data, raw_json_data):
    data_to_use = filtered_json_data
    if data_to_use is None:
        data_to_use = raw_json_data
    
    empty_table_response = [], [], {}, {}, []

    if data_to_use is None:
        return empty_table_response
    
    df = pd.read_json(StringIO(data_to_use), orient='split')

    if df.empty:
        return empty_table_response

    if 'OpenTimestamp' in df.columns:
        df['OpenTimestamp'] = pd.to_datetime(df['OpenTimestamp'], errors='coerce')
    if 'CloseTimestamp' in df.columns:
        df['CloseTimestamp'] = pd.to_datetime(df['CloseTimestamp'], errors='coerce')
    
    display_columns = [
        'TradeID', 'OpenTimestamp', 'CloseTimestamp', 'Symbol', 
        'PositionType', 'EntryPrice', 'ExitPrice', 'Quantity', 'NetP&L'
    ]
    
    final_display_columns = []
    numeric_cols_for_style = ['EntryPrice', 'ExitPrice', 'Quantity', 'NetP&L']
    for col in display_columns:
        if col in df.columns:
            if col in numeric_cols_for_style:
                df[col] = pd.to_numeric(df[col], errors='coerce')
            final_display_columns.append(col)
    
    if 'OpenTimestamp' in final_display_columns and 'OpenTimestamp' in df.columns:
        if pd.api.types.is_datetime64_any_dtype(df['OpenTimestamp']):
            df['OpenTimestamp_display'] = df['OpenTimestamp'].dt.strftime('%Y-%m-%d %H:%M')
        else:
            df['OpenTimestamp_display'] = df['OpenTimestamp'].astype(str)
    else:
        df['OpenTimestamp_display'] = ""


    if 'CloseTimestamp' in final_display_columns and 'CloseTimestamp' in df.columns:
        if pd.api.types.is_datetime64_any_dtype(df['CloseTimestamp']):
            df['CloseTimestamp_display'] = df['CloseTimestamp'].dt.strftime('%Y-%m-%d %H:%M')
        elif pd.Series(df['CloseTimestamp']).notna().any():
             df['CloseTimestamp_display'] = df['CloseTimestamp'].astype(str)
        else:
            df['CloseTimestamp_display'] = ""
    else:
         df['CloseTimestamp_display'] = ""

    
    data_for_table = df[final_display_columns].copy()
    if 'OpenTimestamp_display' in df.columns:
        data_for_table['OpenTimestamp'] = df['OpenTimestamp_display']
    if 'CloseTimestamp_display' in df.columns:
        data_for_table['CloseTimestamp'] = df['CloseTimestamp_display']

    table_data = data_for_table.to_dict('records')
    
    table_columns = []
    for col_id in final_display_columns:
        col_name = col_id
        if col_id == 'OpenTimestamp_display': col_name = 'OpenTimestamp'
        if col_id == 'CloseTimestamp_display': col_name = 'CloseTimestamp'

        if col_id == 'NetP&L':
            table_columns.append({
                "name": col_name, 
                "id": col_id, 
                "type": "numeric",
                "format": dash_table.FormatTemplate.money(2)
            })
        elif col_id in ['EntryPrice', 'ExitPrice', 'Quantity']:
             table_columns.append({"name": col_name, "id": col_id, "type": "numeric"})
        else:
            table_columns.append({"name": col_name, "id": col_id})

    style_header={
        'backgroundColor': '#343a40',
        'color': '#f0f0f0',
        'fontWeight': 'bold',
        'border': '1px solid #444'
    }
    
    style_cell={
        'height': 'auto',
        'minWidth': '80px', 'width': '100px', 'maxWidth': '180px',
        'whiteSpace': 'normal',
        'padding': '8px',
        'textAlign': 'left',
        'backgroundColor': '#23232A', 
        'color': '#f0f0f0',
        'border': '1px solid #444'
    }
    
    style_data_conditional=[
        {
            'if': {'row_index': 'odd'},
            'backgroundColor': '#2E2E36'
        },
        {
            'if': {'row_index': 'even'},
            'backgroundColor': '#23232A'
        },
        {
            'if': {
                'filter_query': '{NetP&L} > 0',
            },
            'backgroundColor': 'rgba(40, 167, 69, 0.3)',
            'color': '#f0f0f0' 
        },
        {
            'if': {
                'filter_query': '{NetP&L} < 0',
            },
            'backgroundColor': 'rgba(220, 53, 69, 0.3)',
            'color': '#f0f0f0'
        },
        { 
            'if': {
                'filter_query': '{NetP&L} = 0',
            },
            'backgroundColor': '#3a3a40', 
            'color': '#f0f0f0'
        },
        {
            'if': {'column_type': 'numeric'},
            'textAlign': 'right'
        },
        {
            'if': {'state': 'active'}, 
            'backgroundColor': 'rgba(0, 123, 255, 0.15)',
            'border': '1px solid #007bff'
        }
    ]
    
    return table_data, table_columns, style_header, style_cell, style_data_conditional


# Register advanced callbacks
advanced_dashboard.register_advanced_callbacks(app)

# Register filter callbacks
global_filters.register_filter_callbacks(app)

# Register journal management callbacks
journal_management.register_journal_callbacks(app)

# Define sidebar states
SIDEBAR_STATES = [
    {
        'name': 'EXPANDED',
        'width': '430px',  # MODIFIED
        'marginLeft': '430px',  # MODIFIED
        'sidebar_class': 'sidebar-active p-3 sidebar-expanded',
        'content_class': 'content-shifted'
    },
    {
        'name': 'ICON_ONLY',
        'width': '80px',
        'marginLeft': '80px',
        'sidebar_class': 'sidebar-active p-3 sidebar-icon-only',
        'content_class': 'content-shifted-narrow'
    }
]

# Callback to toggle sidebar visibility
@app.callback(
    [Output('sidebar', 'className'),
     Output('page-content-wrapper', 'className'),
     Output('page-content-wrapper', 'style'),
     Output('sidebar', 'style'),
     Output('sidebar-state-store', 'data')],
    [Input('sidebar-toggle-button', 'n_clicks')],
    [State('sidebar-state-store', 'data')]
)
def toggle_sidebar_visibility(n_clicks, current_state_index):
    if n_clicks is None or n_clicks == 0:  # Initial load
        # Default to EXPANDED state (index 0)
        initial_state_index = 0
        initial_state = SIDEBAR_STATES[initial_state_index]
        return initial_state['sidebar_class'], initial_state['content_class'], {'marginLeft': initial_state['marginLeft']}, {'width': initial_state['width']}, initial_state_index

    # Determine the next state index by toggling between 0 and 1
    # If current_state_index is 0 (EXPANDED), next is 1 (ICON_ONLY)
    # If current_state_index is 1 (ICON_ONLY), next is 0 (EXPANDED)
    next_state_index = 1 if current_state_index == 0 else 0
    next_state = SIDEBAR_STATES[next_state_index]

    sidebar_style = {'width': next_state['width']}
    page_content_style = {'marginLeft': next_state['marginLeft']}

    return next_state['sidebar_class'], next_state['content_class'], page_content_style, sidebar_style, next_state_index

# Callback to display page content based on sidebar navigation
@app.callback(
    Output('page-content', 'children'),
    Input('url', 'pathname')
)
def display_page(pathname):
    if pathname == '/overview' or pathname == '/' or pathname is None:
        return overview_section_content
    elif pathname == '/algo-analysis':
        return algo_analysis_section_content
    elif pathname == '/advanced-analytics':
        return advanced_analytics_section_content
    elif pathname == '/trade-details':
        return trade_details_section_content
    elif pathname == '/journal-management':
        return journal_management_section_content
    elif pathname == '/calendar-view':
        return calendar_view.create_calendar_layout()
    elif pathname == '/wmy-analysis': # NEW CONDITION
        return wmy_analysis.create_wmy_layout() # USE THE NEW LAYOUT FUNCTION
    # Default to Overview or a 404 message if preferred
    return overview_section_content

# Register calendar callbacks
# Note: The toggle_modal_close_button callback previously here has been removed.
# Its functionality is now integrated into display_daily_trades_popup in calendar_view.py
calendar_view.register_calendar_callbacks(app)
wmy_analysis.register_wmy_callbacks(app) # ADDED THIS LINE

# Run the app
if __name__ == '__main__':
    # Journal management callbacks are registered earlier in the file if needed
    # Journal management callbacks are registered earlier in the file if needed
    app.run(debug=True, host='0.0.0.0')

[end of app/main.py]
   ```

   For Linux/Nginx users:
   ```bash
   pip install -r requirements-nginx.txt
   ```

4. **Install Node.js Dependencies**: 
   ```bash
   cd openalgo
   npm install
   ```

5. **Configure Environment Variables**: 
   - Rename `.sample.env` to `.env` in the `openalgo` folder
   - Update the `.env` file with your specific configurations

## CSS Compilation Setup

The project uses TailwindCSS and DaisyUI for styling. The CSS needs to be compiled before running the application.

### Development Mode

For development with auto-recompilation (watches for changes):
```bash
npm run dev
```

### Production Build

For production deployment:
```bash
npm run build
```

### CSS File Structure

- Source file: `src/css/styles.css`
- Compiled output: `static/css/main.css`

When making style changes:
1. Edit the source file at `src/css/styles.css`
2. Run the appropriate npm script to compile
3. The compiled CSS will be automatically used by the templates

## Running the Application

1. **Start the Flask Application**: 

   For development:
   ```bash
   python app.py
   ```

   For production with Nginx (using eventlet):
   ```bash
   gunicorn --worker-class eventlet -w 1 app:app
   ```

   Note: When using Gunicorn, `-w 1` specifies one worker process. This is important because WebSocket connections are persistent and stateful.

2. **Access the Application**:
   - Open your browser and navigate to [http://127.0.0.1:5000](http://127.0.0.1:5000)
   - Set up your account at [http://127.0.0.1:5000/setup](http://127.0.0.1:5000/setup)
   - Log in with your credentials

## Troubleshooting

If you encounter any issues during installation:

1. **CSS not updating**:
   - Ensure Node.js is properly installed
   - Run `npm install` again
   - Check if the CSS compilation script is running
   - Clear your browser cache

2. **Python dependencies**:
   - Use a virtual environment
   - Ensure you're using Python 3.10 or 3.11
   - Try upgrading pip: `pip install --upgrade pip`

3. **WebSocket issues**:
   - Ensure you're using only one worker with Gunicorn
   - Check if your firewall allows WebSocket connections
   - Verify Socket.IO client version matches server version

For more detailed configuration instructions, visit [https://docs.openalgo.in](https://docs.openalgo.in)
