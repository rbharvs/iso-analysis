# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "matplotlib",
#     "numpy",
#     "scipy",
#     "pydantic",
# ]
# ///
"""
ISO (Incentive Stock Option) exercise tax calculator.

Finds the ISO exercise "spread" - the dollar amount of bargain element where
AMT equals ordinary income tax. This represents the MAXIMUM you can exercise
without triggering AMT (i.e., without AMT exceeding ordinary tax).

IMPORTANT: "Optimal" means maximizing exercise amount without paying more tax
than you currently do. Beyond this point, AMT exceeds ordinary tax and you'd
pay more. You must decide if this strategy fits your situation.

To convert spread to shares: divide by (FMV - strike_price)
Example: $50k spread ÷ $90/share bargain = 556 shares

USAGE:
    python iso_analysis.py <income>                    # Calculate for single income
    python iso_analysis.py <start_income> <end_income> # Generate plot (saves to PNG file)

UPDATING FOR NEW TAX YEAR:
    1. Find the section marked "UPDATE THESE SCHEDULES EACH YEAR"
    2. Update ORDINARY_SCHEDULE with new year's values from IRS Publication 17
    3. Update AMT_SCHEDULE with new year's values from IRS Form 6251
    4. Done!

IMPORTANT ASSUMPTIONS:
    This is a simplified model suitable for ISO exercise planning. It assumes:
    - Taxpayer takes standard deduction (not itemizing)
    - Primary AMT concern is ISO exercise spread
    - No significant other AMT preference items

    The model is accurate because:
    - Standard deduction is added back for AMT (per Form 6251), so it cancels out
    - AMT exemption replaces the standard deduction (per IRS/mystockoptions.com)
    - AMTI effectively equals gross income + ISO spread for standard deduction filers

    For actual tax filing or if itemizing deductions (especially with large SALT),
    use professional tax software or consult a CPA. This tool is for planning only.
"""

import numpy as np
import scipy.optimize
import sys
import matplotlib.pyplot as plt
from pydantic import BaseModel, Field, field_validator
from typing import Optional


class TaxBracket(BaseModel):
    """Tax bracket with standard marginal rate."""

    threshold: float = Field(ge=0, description="Income level where this rate begins")
    rate: float = Field(ge=0, le=1, description="Marginal tax rate for this bracket")


class Exemption(BaseModel):
    """
    Amount subtracted from income before applying tax brackets.

    Represents either:
    - Standard deduction (ordinary tax): fixed amount, no phaseout
    - AMT exemption: base amount that phases out at high income

    NOTE: For AMT, the exemption REPLACES the standard deduction (per IRS Form 6251).
    The standard deduction is added back when calculating AMTI, so AMTI effectively
    equals gross income + ISO spread. The AMT exemption is then subtracted from AMTI.

    Sources:
    - IRS Form 6251 (Alternative Minimum Tax—Individuals)
    - myStockOptions.com AMT calculation guides
    """

    base_amount: float = Field(ge=0, description="Base exemption/deduction amount")
    phaseout_start: Optional[float] = Field(
        ge=0,
        default=None,
        description="Income level where exemption begins to phase out",
    )
    phaseout_rate: Optional[float] = Field(
        ge=0,
        le=1,
        default=None,
        description="Rate at which exemption reduces (typically 0.25 for AMT)",
    )

    def compute(self, income: float) -> float:
        """
        Calculate actual exemption amount for given income.

        For standard deductions: always returns base_amount
        For AMT exemptions: reduces by phaseout_rate above phaseout_start
        """
        exemption = self.base_amount

        if self.phaseout_start is not None and self.phaseout_rate is not None:
            if income > self.phaseout_start:
                reduction = self.phaseout_rate * (income - self.phaseout_start)
                exemption = max(exemption - reduction, 0)

        return exemption


class TaxSchedule(BaseModel):
    """
    Unified tax calculation schedule for any tax system.

    Works for:
    - Ordinary income tax (with standard deduction)
    - Alternative Minimum Tax (with phasing exemption)
    - Any other progressive tax system
    """

    year: int = Field(ge=2000, le=2100)
    filing_status: str = Field(description="e.g., 'Single', 'MFJ', 'MFS', 'HOH'")
    name: str = Field(description="'Ordinary' or 'AMT' or custom name")

    exemption: Exemption = Field(
        description="Deduction/exemption applied before brackets"
    )
    brackets: list[TaxBracket] = Field(min_length=1)

    @field_validator("brackets")
    @classmethod
    def brackets_must_be_sorted(cls, v: list[TaxBracket]) -> list[TaxBracket]:
        """Ensure brackets are in ascending order by threshold."""
        thresholds = [b.threshold for b in v]
        if thresholds != sorted(thresholds):
            raise ValueError("Tax brackets must be sorted by threshold")
        return v

    def compute_tax(self, income: float) -> float:
        """
        Calculate tax for given income.

        Algorithm:
        1. Calculate exemption (with phaseout if applicable)
        2. Subtract from income to get taxable amount
        3. Apply progressive brackets to taxable amount

        For ordinary tax:
        - income = gross income (W-2, etc.)
        - exemption = standard deduction
        - Taxable income = income - standard deduction

        For AMT (per IRS Form 6251):
        - income = AMTI (Alternative Minimum Taxable Income)
        - AMTI = gross income + ISO spread (standard deduction is added back)
        - exemption = AMT exemption (replaces standard deduction)
        - AMT base = AMTI - AMT exemption
        - Note: Standard deduction is NOT allowed for AMT and gets added back
          to AMTI, so it effectively cancels out

        Args:
            income: Gross income for ordinary tax, or AMTI for AMT

        Returns:
            Tax amount owed
        """
        if income < 0:
            raise ValueError("Income cannot be negative")

        # Step 1: Calculate exemption
        exemption = self.exemption.compute(income)

        # Step 2: Calculate taxable income
        taxable = income - exemption
        if taxable <= 0:
            return 0.0

        # Step 3: Apply brackets
        tax = 0.0
        for i, bracket in enumerate(self.brackets):
            # Determine the upper bound for this bracket
            next_threshold = (
                self.brackets[i + 1].threshold
                if i + 1 < len(self.brackets)
                else float("inf")
            )

            if taxable <= bracket.threshold:
                # Income doesn't reach this bracket
                break

            # Calculate tax for the portion of income in this bracket
            bracket_top = min(taxable, next_threshold)
            taxable_in_bracket = bracket_top - bracket.threshold
            tax += taxable_in_bracket * bracket.rate

        return tax


################################################################################
# UPDATE THESE SCHEDULES EACH YEAR
################################################################################
#
# To update for a new tax year:
#   1. Change the year value (e.g., 2025 → 2026)
#   2. Update filing_status if needed ("Single", "MFJ", "MFS", "HOH")
#   3. Update the exemption base_amount (standard deduction or AMT exemption)
#   4. Update bracket thresholds and rates from IRS tables
#   5. For AMT, update phaseout_start and phaseout_rate if changed
#
################################################################################

# 2025 Ordinary Income Tax (Single Filer)
ORDINARY_SCHEDULE = TaxSchedule(
    year=2025,
    filing_status="Single",  # Single, MFJ, MFS, HOH
    name="Ordinary",
    exemption=Exemption(
        base_amount=15750,  # Standard deduction for Single 2025
    ),
    brackets=[
        # Copy these directly from IRS tax tables (use actual marginal rates)
        TaxBracket(threshold=0, rate=0.10),  # 10% on first $11,925
        TaxBracket(threshold=11925, rate=0.12),  # 12% on $11,925 - $48,475
        TaxBracket(threshold=48475, rate=0.22),  # 22% on $48,475 - $103,350
        TaxBracket(threshold=103350, rate=0.24),  # 24% on $103,350 - $197,300
        TaxBracket(threshold=197300, rate=0.32),  # 32% on $197,300 - $250,525
        TaxBracket(threshold=250525, rate=0.35),  # 35% on $250,525 - $626,350
        TaxBracket(threshold=626350, rate=0.37),  # 37% on $626,350+
    ],
)

# 2025 Alternative Minimum Tax (Single Filer)
AMT_SCHEDULE = TaxSchedule(
    year=2025,
    filing_status="Single",  # Should match ORDINARY_SCHEDULE
    name="AMT",
    exemption=Exemption(
        base_amount=88100,  # AMT exemption amount for Single 2025
        phaseout_start=626350,  # Income level where exemption starts to phase out
        phaseout_rate=0.25,  # Exemption reduces by 25¢ per $1 over threshold
    ),
    brackets=[
        # AMT has only 2 brackets
        TaxBracket(threshold=0, rate=0.26),  # 26% on first $239,100
        TaxBracket(threshold=239100, rate=0.28),  # 28% on $239,100+
    ],
)


def compute_spread(
    income: float, ordinary_schedule: TaxSchedule, amt_schedule: TaxSchedule
) -> float:
    """
    Calculate the ISO exercise spread.

    Finds the dollar amount of ISO bargain element where AMT equals ordinary tax.

    IMPORTANT: This is "optimal" ONLY if your goal is to maximize ISO exercise
    without triggering AMT (i.e., without AMT exceeding ordinary tax). Beyond this
    point, AMT would exceed ordinary tax and you'd pay MORE than you currently do.

    To convert the spread to number of shares to exercise:
        shares_to_exercise = spread / (FMV - strike_price)

    where:
        FMV = fair market value per share at exercise
        strike_price = your exercise price per share

    Example:
        spread = $50,000
        FMV = $100/share
        strike = $10/share
        shares = $50,000 / ($100 - $10) = 556 shares

    Args:
        income: Base income (W-2, etc.) before ISO exercise
        ordinary_schedule: Ordinary tax schedule
        amt_schedule: AMT schedule

    Returns:
        Dollar amount of ISO bargain element (spread) where AMT = ordinary tax
    """

    def objective(additional_income: np.ndarray) -> np.ndarray:
        total_income = additional_income[0]
        amt_tax = amt_schedule.compute_tax(total_income)
        ordinary_tax = ordinary_schedule.compute_tax(income)
        return np.array([amt_tax - ordinary_tax])

    # Initial guess: base income + AMT exemption
    initial_guess = income + amt_schedule.exemption.base_amount
    result = scipy.optimize.root(objective, np.array([initial_guess]))

    return result.x[0] - income


def main():
    """Main CLI entry point."""
    if len(sys.argv) < 2:
        print("Usage:")
        print("  python iso_analysis.py <income>")
        print(
            "  python iso_analysis.py <start_income> <end_income>  (saves plot to PNG)"
        )
        return

    if len(sys.argv) == 2:
        # Single income calculation
        income = float(sys.argv[1])
        ordinary_tax = ORDINARY_SCHEDULE.compute_tax(income)
        amt_tax = AMT_SCHEDULE.compute_tax(income)
        spread = compute_spread(income, ORDINARY_SCHEDULE, AMT_SCHEDULE)

        print(
            f"\n{ORDINARY_SCHEDULE.year} Tax Analysis ({ORDINARY_SCHEDULE.filing_status})"
        )
        print(f"{'=' * 50}")
        print(f"Income:          ${income:,.2f}")
        print(f"Ordinary tax:    ${ordinary_tax:,.2f}")
        print(f"AMT:             ${amt_tax:,.2f}")
        print(f"ISO spread:      ${spread:,.2f}")
        print(f"{'=' * 50}\n")

    elif len(sys.argv) == 3:
        # Range analysis with plot
        start = float(sys.argv[1])
        end = float(sys.argv[2])

        x_values = np.arange(start, end + 10, 10)
        y_values = [
            compute_spread(x, ORDINARY_SCHEDULE, AMT_SCHEDULE) for x in x_values
        ]

        min_idx = np.argmin(y_values)
        min_spread = y_values[min_idx]
        min_income = x_values[min_idx]

        print(
            f"\n{ORDINARY_SCHEDULE.year} ISO Spread Analysis ({ORDINARY_SCHEDULE.filing_status})"
        )
        print(f"{'=' * 50}")
        print(f"Income range:    ${start:,.0f} - ${end:,.0f}")
        print(f"Minimum spread:  ${min_spread:,.2f}")
        print(f"At income:       ${min_income:,.0f}")
        print(f"{'=' * 50}\n")

        plt.figure(figsize=(12, 7))
        plt.plot(x_values, y_values, linewidth=2)
        plt.xlabel("Base Income ($)", fontsize=12)
        plt.ylabel("ISO Exercise Spread ($)", fontsize=12)
        plt.title(
            f"{ORDINARY_SCHEDULE.year} ISO Exercise Spread vs Income ({ORDINARY_SCHEDULE.filing_status})",
            fontsize=14,
        )
        plt.grid(True, alpha=0.3)
        plt.axvline(
            min_income,
            color="r",
            linestyle="--",
            alpha=0.5,
            label=f"Min at ${min_income:,.0f}",
        )
        plt.axhline(
            min_spread,
            color="r",
            linestyle="--",
            alpha=0.5,
            label=f"Min spread: ${min_spread:,.2f}",
        )
        plt.legend()
        plt.tight_layout()

        # Save plot instead of showing
        filename = f"iso_spread_{ORDINARY_SCHEDULE.year}_{ORDINARY_SCHEDULE.filing_status}_{int(start)}-{int(end)}.png"
        plt.savefig(filename, dpi=150, bbox_inches="tight")
        plt.close()
        print(f"\nPlot saved to: {filename}")
    else:
        print("Error: Invalid number of arguments")


if __name__ == "__main__":
    main()
