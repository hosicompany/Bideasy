from app.services.calculator import CalculatorService
import math

def test_calculator():
    print("Running Calculator Verification...")
    
    # Test Case 1: Simple Calculation
    price = 1000000
    rate = 1.2345
    expected = price * (1 + rate / 100)
    expected_truncated = math.floor(expected / 10) * 10
    
    result = CalculatorService.calculate_safe_bid(price, rate)
    
    print(f"Input: {price}, Rate: {rate}%")
    print(f"Expected (Truncated): {expected_truncated}")
    print(f"Result: {result}")
    
    assert result == expected_truncated
    assert result % 10 == 0
    print("✅ Test Case 1 Passed")

    # Test Case 2: Edge Case (Already multiple of 10)
    price2 = 1000
    rate2 = 0.0
    result2 = CalculatorService.calculate_safe_bid(price2, rate2)
    assert result2 == 1000
    print("✅ Test Case 2 Passed (Identity)")

    # Test Case 3: 1 won truncation check
    # 100 * 1.011 = 101.1 -> floor(10.11)*10 = 100? No.
    # 101.1 / 10 = 10.11 -> floor -> 10 -> 10 * 10 = 100. Correct.
    # Wait, 101 won should be strictly preserved?
    # Rule: "1원 단위 절사" means removing the 1s digit. 123 -> 120.
    # Let's verify manual calc:
    # Price 1005, Rate 0.
    # Result should be 1000.
    
    res3 = CalculatorService.calculate_safe_bid(1005, 0)
    print(f"1005 -> {res3}")
    assert res3 == 1000
    print("✅ Test Case 3 Passed (1s digit truncation)")
    
    print("All verification passed!")

if __name__ == "__main__":
    test_calculator()
