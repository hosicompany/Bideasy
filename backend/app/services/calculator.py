import math

class CalculatorService:
    @staticmethod
    def get_lower_limit_rate(contract_type: str) -> float:
        """
        Get standard Lower Limit Rate (Nakchalhahan-yul)
        """
        # Standard Public Procurement Service Rates (Approx)
        if contract_type == "CONSTRUCTION":
            return 87.745 # 87.745%
        elif contract_type == "SERVICE":
            return 87.995 # 87.995%
        elif contract_type == "GOODS":
            return 88.0 # 88.0%
        return 87.745 # Default

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
