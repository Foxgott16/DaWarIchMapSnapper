<div align="center" style="color: #c00; font-size: 28px; font-weight: bold; border: 4px solid #c00; padding: 24px; margin: 24px 0; background: #ffe0e0;">

# ⚠️ DISCLAIMER ⚠️

**THIS SOFTWARE IS HEAVILY VIBE-CODED.**  
**ANY DATA SHOULD BE HANDLED WITH EXTREME CAUTION.**  
**USE AT YOUR OWN RISK.**

</div>

---

# DaWarIchMapSnapper

This is a heavily vibe-coded solution to snap GeoJSON tracks to streets using Geoapify to fix bad tracking.

I used the free tier of Geoapify; you just have to keep in mind the limits of the tier. For short trips, this is fine. For bulk, you should self-host and try something like this: https://spatialthoughts.com/2020/02/22/snap-to-roads-qgis-and-osrm/

## How to

- Go to https://geoapify.com and create an account
- Go to https://myprojects.geoapify.com/projects and create a new project
- Navigate to API keys and copy the API key that has been created for you
- Paste this API key into the `config.ini` file after `api_key = ` (don't forget the space there)
- Make sure you have Python installed
- Start the UI with `run_geojson_tool.bat`
- Load the GeoJSON you exported from DaWarIch
- The final response will be named accordingly and you can find it in the same folder the input came from
