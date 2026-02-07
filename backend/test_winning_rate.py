import sys
import os

# Add backend to path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from app.db.session import SessionLocal
from app.services.winning_rate import WinningRateService

def check_service():
    db = SessionLocal()
    agency = "TestOrg" # Matches dummy data
    
    print(f"1. Testing Agency Stats for '{agency}'...")
    stats = WinningRateService.get_agency_stats(db, agency)
    print(f"   -> Result: {stats}")
    
    print("\n2. Testing Monte Carlo Logic...")
    # Using basic stats
    sim_results = WinningRateService.run_monte_carlo_simulation(100.0, stats)
    print(f"   -> Generated {len(sim_results)} simulations")
    print(f"   -> Sample: {sim_results[:3]}")
    
    print("\n3. Testing Blue Ocean...")
    blue_ocean = WinningRateService.get_blue_ocean_strategy(db, "TEST-NO")
    print(f"   -> {blue_ocean}")
    
    db.close()

if __name__ == "__main__":
    check_service()
