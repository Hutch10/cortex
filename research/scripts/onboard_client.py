import sqlite3
import uuid
from datetime import datetime

def onboard_new_client():
    print("--- HutchSolves Cortex | New Client Intake ---")
    client_name = input("Enter Client/Business Name: ")
    tail_number = input("Enter Primary Tail Number: ")
    home_base   = input("Enter Home Base ICAO: ")
    
    tenant_id = f"tenant-{uuid.uuid4().hex[:8]}"
    
    conn = sqlite3.connect('cortex.sqlite')
    cursor = conn.cursor()
    
    # COMMERCIAL SCHEMA INITIALIZATION
    cursor.execute("""CREATE TABLE IF NOT EXISTS tenants 
                      (tenant_id TEXT PRIMARY KEY, name TEXT, base_icao TEXT, status TEXT)""")
    cursor.execute("""CREATE TABLE IF NOT EXISTS assets 
                      (tenant_id TEXT, tail_number TEXT, status TEXT)""")
    
    # 1. Create the Tenant Record
    cursor.execute("INSERT INTO tenants (tenant_id, name, base_icao, status) VALUES (?, ?, ?, ?)",
                   (tenant_id, client_name, home_base, 'ACTIVE'))
    
    # 2. Initialize the Asset
    cursor.execute("INSERT INTO assets (tenant_id, tail_number, status) VALUES (?, ?, ?)",
                   (tenant_id, tail_number, 'ONBOARDING'))
    
    conn.commit()
    conn.close()
    
    print(f"\n[SUCCESS] Welcome, {client_name}!")
    print(f"TENANT ID : {tenant_id}")
    print(f"NEXT STEP : Establish the 'Iron Delta' baseline.")

if __name__ == "__main__":
    onboard_new_client()
