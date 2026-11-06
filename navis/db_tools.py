import pandas as pd
import regex as re
import numpy as np
import webbrowser
import requests
import json



PLATFORMTYPE = "&PLATFORM_TYPE=NAVIS_EBR"
BASE_URL = "https://db.whoifloatgroup.org"
#BASE_URL = "http://127.0.0.1:8000"

headers = {'Content-Type':'application/json'}

def get_cal(PLATFORM_NUMBER):
    response = requests.get(BASE_URL+"/api/cal",headers=headers,
        params={"PLATFORM_NUMBER":PLATFORM_NUMBER})

    if response.status_code==200:
        return pd.DataFrame(json.loads(response.content))
    raise Exception('ERROR: ', response.status_code)

def last_cycle(PLATFORM_NUMBER):
    response = requests.get(BASE_URL+"/api/latest_cycle",headers=headers,
        params={"PLATFORM_NUMBER":PLATFORM_NUMBER})
    
    if response.status_code == 200:
        results = json.loads(response.content)
        return results["last_cycle"]
    raise Exception('ERROR: ', response.status_code)
    
def get_discrete_profile_stats(PLATFORM_NUMBER):
    response = requests.get(BASE_URL+"/api/discrete_profile_stats", headers=headers, 
        params={"PLATFORM_NUMBER":PLATFORM_NUMBER})

    if response.status_code==200:
        return pd.DataFrame(json.loads(response.content))
    raise Exception('ERROR: ', response.status_code)

def get_continuous_profile_stats(PLATFORM_NUMBER):  
    response = requests.get(BASE_URL+"/api/continuous_profile_stats", headers=headers, 
        params={"PLATFORM_NUMBER":PLATFORM_NUMBER})

    if response.status_code==200:
        return pd.DataFrame(json.loads(response.content))
    raise Exception('ERROR: ', response.status_code)

def get_discrete_one_float(PLATFORM_NUMBER, output_fields):
    response = requests.get(BASE_URL+"/api/discrete_data_get", headers=headers, 
        params={"DEPLOYMENT__PLATFORM_NUMBER":PLATFORM_NUMBER, "output_fields":output_fields})

    if response.status_code==200:
        return pd.DataFrame(json.loads(response.content))
    raise Exception('ERROR: ', response.status_code)

def get_discrete_one_profile(PROFILE_ID, output_fields):
    response = requests.get(BASE_URL+"/api/discrete_data_get", headers=headers, 
        params={"PROFILE_ID":PROFILE_ID, "output_fields":output_fields})

    if response.status_code==200:
        return pd.DataFrame(json.loads(response.content))
    raise Exception('ERROR: ', response.status_code)

def get_continuous_one_float(PLATFORM_NUMBER, output_fields):
    response = requests.get(BASE_URL+"/api/continuous_data_get", headers=headers, 
        params={"DEPLOYMENT__PLATFORM_NUMBER":PLATFORM_NUMBER, "output_fields":output_fields})

    if response.status_code==200:
        return pd.DataFrame(json.loads(response.content))
    raise Exception('ERROR: ', response.status_code)

def get_continuous_one_profile(PROFILE_ID, output_fields):
    response = requests.get(BASE_URL+"/api/continuous_data_get", headers=headers, 
        params={"PROFILE_ID":PROFILE_ID, "output_fields":output_fields})

    if response.status_code==200:
        return pd.DataFrame(json.loads(response.content))
    raise Exception('ERROR: ', response.status_code)

def get_engineering_all(output_fields):
    response = requests.get(BASE_URL+"/api/cycle_meta_get", headers=headers, 
        params={"output_fields":output_fields})

    if response.status_code==200:
        return pd.DataFrame(json.loads(response.content))
    raise Exception('ERROR: ', response.status_code)

def get_park_all(output_fields):
    response = requests.get(BASE_URL+"/api/park_data_get", headers=headers, 
        params={"output_fields":output_fields})

    if response.status_code==200:
        return pd.DataFrame(json.loads(response.content))
    raise Exception('ERROR: ', response.status_code)   

def get_surface_all(output_fields):
    response = requests.get(BASE_URL+"/api/surface_observations_get", headers=headers, 
        params={"output_fields":output_fields})

    if response.status_code==200:
        return pd.DataFrame(json.loads(response.content))
    raise Exception('ERROR: ', response.status_code)

def get_metadata_all(output_fields):
    response = requests.get(BASE_URL+"/api/deployment_metadata", headers=headers, 
        params={"deployment_fields":output_fields, "PLATFORM_TYPE":"NAVIS_EBR"})

    if response.status_code==200:
        return pd.DataFrame(json.loads(response.content))
    raise Exception('ERROR: ', response.status_code)
    
def get_cal(PLATFORM_NUMBER):
    response = requests.get(BASE_URL+"/api/cal",headers=headers,
        params={"PLATFORM_NUMBER":PLATFORM_NUMBER})

    if response.status_code==200:
        return pd.DataFrame(json.loads(response.content))
    raise Exception('ERROR: ', response.status_code)

def get_cal_sn(floatnum):
    floatnum = "FLOAT_SERIAL_NO=" + str(floatnum) + PLATFORMTYPE
    response = requests.get(BASE_URL+"/api/cal?"+floatnum)

    if response.status_code==200:
        return pd.DataFrame(json.loads(response.content))
    raise Exception('ERROR: ', response.status_code)

def make_clickable(val):
    return f'<a target="_blank" href="{val}">{val}</a>'

def generate_html(dataframe: pd.DataFrame):
    # get the table HTML from the dataframe
    table_html = dataframe.to_html(render_links=True, table_id="table")
    # construct the complete HTML with jQuery Data tables
    # You can disable paging or enable y scrolling on lines 20 and 21 respectively
    html = f"""
    <html>
    <header>
        <link href="https://cdn.datatables.net/1.11.5/css/jquery.dataTables.min.css" rel="stylesheet">
    </header>
    <body>
    {table_html}
    <script src="https://code.jquery.com/jquery-3.6.0.slim.min.js" integrity="sha256-u7e5khyithlIdTpu22PHhENmPcRdFiHRjhAuHcs05RI=" crossorigin="anonymous"></script>
    <script type="text/javascript" src="https://cdn.datatables.net/1.11.5/js/jquery.dataTables.min.js"></script>
    <script>
        $(document).ready( function () {{
            $('#table').DataTable({{
                // paging: false,    
                // scrollY: 400,
            }});
        }});
    </script>
    </body>
    </html>
    """
    return html

