import math

class CalculatorService:
    @staticmethod
    def calculate_safe_bid(basic_price: float, rate: float) -> int:
        """
        Calculate safe bid price with 1 won truncation.
        Formula: math.floor(price / 10) * 10
        """
        target_price = basic_price * (1 + rate / 100)
        # Apply truncation rule
        final_price = math.floor(target_price / 10) * 10
        return final_price
