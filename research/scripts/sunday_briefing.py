import sqlite3
import argparse
from datetime import datetime

def generate_pro_briefing(tenant_id):
    conn = sqlite3.connect('cortex.sqlite')
    cursor = conn.cursor()
    
    # Fetch chronological health data for THIS tenant only
    cursor.execute("""SELECT iron_ppm, flight_hours, report_date 
                      FROM asset_health 
                      WHERE tenant_id = ? 
                      ORDER BY flight_hours ASC""", (tenant_id,))
    reports = cursor.fetchall()
    
    status = "STABLE"
    rate_note = "Engine wear metrics nominal."
    
    if len(reports) >= 2:
        # Compare the two most recent reports
        p_iron, p_hours, _ = reports[-2]
        l_iron, l_hours, _ = reports[-1]
        
        delta_iron = l_iron - p_iron
        delta_hours = l_hours - p_hours
        
        if delta_hours > 0:
            rate = delta_iron / delta_hours
            # Industry Standard: > 0.5 ppm per hour is a 'Caution', > 1.0 is 'Critical'
            if rate >= 1.0:
                status = "CRITICAL"
                rate_note = f"SEVERE WEAR: {rate:.2f} ppm/hr detected. Immediate inspection required."
            elif rate > 0.5:
                status = "CAUTION"
                rate_note = f"ELEVATED WEAR: {rate:.2f} ppm/hr detected. Monitor closely."
            else:
                rate_note = f"Wear rate stable at {rate:.2f} ppm/hr."

    print(f"\n--- Sentinel Pro Briefing | Tenant: {tenant_id} ---")
    print(f"OVERALL STATUS : {status}")
    print(f"DIAGNOSTIC     : {rate_note}")
    conn.close()

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument('--tenant', type=str, required=True)
    args = parser.parse_args()
    generate_pro_briefing(args.tenant)
