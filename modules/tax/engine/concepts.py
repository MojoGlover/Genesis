"""
concepts.py — Core US Federal Tax Concepts
===========================================
Plain-language definitions of every concept used in this engine.
An AI can load this dict and explain any term to the user.
"""

TAX_CONCEPTS = {

    # ── Income ─────────────────────────────────────────────────────────────────
    "gross_income": {
        "term": "Gross Income",
        "plain": "Everything you earned before any deductions or taxes. All wages, "
                 "tips, freelance pay, investment gains, rental income, and other income.",
        "irs_ref": "IRC §61",
        "line_1040": "Lines 1-8"
    },
    "agi": {
        "term": "Adjusted Gross Income (AGI)",
        "plain": "Gross income minus 'above-the-line' deductions like student loan interest, "
                 "IRA contributions, HSA contributions, and self-employment tax. "
                 "AGI is the foundation — many limits and phaseouts are based on it.",
        "irs_ref": "IRC §62",
        "line_1040": "Line 11"
    },
    "taxable_income": {
        "term": "Taxable Income",
        "plain": "AGI minus either the standard deduction OR itemized deductions "
                 "(whichever is larger). This is the number your tax brackets are applied to.",
        "irs_ref": "IRC §63",
        "line_1040": "Line 15"
    },
    "earned_income": {
        "term": "Earned Income",
        "plain": "Money from working: wages, salaries, tips, self-employment. "
                 "Does NOT include investment income or rental income.",
        "irs_ref": "IRC §32(c)(2)"
    },
    "passive_income": {
        "term": "Passive Income",
        "plain": "Income from activities you don't actively participate in — "
                 "typically rental income or limited partnership income. "
                 "Passive losses can only offset passive gains.",
        "irs_ref": "IRC §469"
    },
    "unearned_income": {
        "term": "Unearned Income",
        "plain": "Income from investments: dividends, interest, capital gains. "
                 "Often taxed at different (sometimes lower) rates than earned income.",
        "irs_ref": "IRC §1(h)"
    },

    # ── Deductions ─────────────────────────────────────────────────────────────
    "standard_deduction": {
        "term": "Standard Deduction",
        "plain": "A flat dollar amount the IRS lets you subtract from AGI without "
                 "needing receipts. Amount depends on filing status and is adjusted "
                 "for inflation each year. Most people take this.",
        "irs_ref": "IRC §63(c)"
    },
    "itemized_deductions": {
        "term": "Itemized Deductions",
        "plain": "Specific expenses you list on Schedule A instead of taking the "
                 "standard deduction. Only worth it if your total exceeds the standard "
                 "deduction. Common items: mortgage interest, state taxes (capped), "
                 "charity, large medical expenses.",
        "irs_ref": "IRC §§161-224, Schedule A"
    },
    "above_the_line": {
        "term": "Above-the-Line Deductions",
        "plain": "Deductions you can take regardless of whether you itemize or not. "
                 "They reduce AGI directly. Examples: IRA contributions, student loan "
                 "interest, HSA contributions, half of self-employment tax.",
        "irs_ref": "IRC §62"
    },
    "salt": {
        "term": "SALT (State and Local Tax Deduction)",
        "plain": "The deduction for state income taxes (or sales taxes) plus property taxes. "
                 "Currently capped at $10,000 per year (2018–2025 under TCJA). "
                 "This cap is on Schedule A (itemized only).",
        "irs_ref": "IRC §164(b)(6)"
    },
    "mortgage_interest": {
        "term": "Mortgage Interest Deduction",
        "plain": "Interest paid on a home loan is deductible on Schedule A. "
                 "Limited to interest on up to $750,000 of mortgage debt (post-2017 loans). "
                 "Pre-2017 loans: up to $1M limit.",
        "irs_ref": "IRC §163(h)"
    },
    "qbi": {
        "term": "Qualified Business Income (QBI) Deduction",
        "plain": "Self-employed people and pass-through business owners (LLC, S-Corp, partnership) "
                 "can deduct up to 20% of qualified business income. Has income limits and "
                 "restrictions for service businesses. Created by TCJA — expires after 2025.",
        "irs_ref": "IRC §199A"
    },

    # ── Credits ────────────────────────────────────────────────────────────────
    "tax_credit": {
        "term": "Tax Credit",
        "plain": "A dollar-for-dollar reduction of the tax you owe. A $1,000 credit "
                 "saves you exactly $1,000 in taxes. More valuable than a deduction. "
                 "Some are refundable (you get money back even if credit exceeds tax owed).",
        "irs_ref": "IRC §§21-54"
    },
    "refundable_credit": {
        "term": "Refundable Credit",
        "plain": "A credit that can reduce your tax below zero — the IRS pays you the "
                 "difference. Example: Earned Income Tax Credit (EITC), Additional "
                 "Child Tax Credit.",
        "irs_ref": "IRC §32"
    },
    "nonrefundable_credit": {
        "term": "Non-Refundable Credit",
        "plain": "A credit that can reduce your tax to zero but not below. "
                 "If you don't owe enough tax to use it fully, you lose the rest. "
                 "Example: Child and Dependent Care Credit.",
        "irs_ref": "IRC §21"
    },
    "child_tax_credit": {
        "term": "Child Tax Credit (CTC)",
        "plain": "Up to $2,000 per qualifying child under age 17. Partially refundable "
                 "(Additional CTC). Phases out at higher income levels. "
                 "Under TCJA (2018–2025); may drop to $1,000 in 2026 if law isn't renewed.",
        "irs_ref": "IRC §24"
    },
    "eitc": {
        "term": "Earned Income Tax Credit (EITC)",
        "plain": "Refundable credit for low-to-moderate income workers. Amount depends "
                 "on income, filing status, and number of children. One of the largest "
                 "anti-poverty programs in the tax code.",
        "irs_ref": "IRC §32"
    },

    # ── Tax Rates & Brackets ───────────────────────────────────────────────────
    "tax_bracket": {
        "term": "Tax Bracket",
        "plain": "The US uses a progressive (marginal) system. Each bracket applies only "
                 "to income in that range — not your whole income. Earning more never "
                 "makes your total tax go down.",
        "irs_ref": "IRC §1"
    },
    "marginal_rate": {
        "term": "Marginal Tax Rate",
        "plain": "The rate on your LAST dollar of income. If you're in the 22% bracket, "
                 "only income in that bracket is taxed at 22%. Your lower income is still "
                 "taxed at lower rates.",
        "irs_ref": "IRC §1"
    },
    "effective_rate": {
        "term": "Effective Tax Rate",
        "plain": "Your total tax divided by your total income. This is what you actually "
                 "pay on average across all income — always lower than the marginal rate.",
        "formula": "effective_rate = total_tax / gross_income"
    },
    "capital_gains_rate": {
        "term": "Capital Gains Tax Rate",
        "plain": "Long-term capital gains (assets held 1+ year) are taxed at 0%, 15%, or 20% "
                 "depending on income — usually lower than ordinary income rates. "
                 "Short-term gains (under 1 year) are taxed as ordinary income.",
        "irs_ref": "IRC §1(h)"
    },

    # ── Filing ─────────────────────────────────────────────────────────────────
    "filing_status": {
        "term": "Filing Status",
        "plain": "Determines your bracket thresholds and standard deduction. Options: "
                 "Single, Married Filing Jointly (MFJ), Married Filing Separately (MFS), "
                 "Head of Household (HoH), Qualifying Surviving Spouse.",
        "irs_ref": "IRC §§1, 2"
    },
    "withholding": {
        "term": "Withholding",
        "plain": "Taxes your employer already took out of your paychecks and sent to the IRS. "
                 "Shown on your W-2 Box 2. Your refund or balance-due is calculated "
                 "after subtracting this from total tax owed.",
        "irs_ref": "IRC §3402"
    },
    "estimated_tax": {
        "term": "Estimated Tax Payments",
        "plain": "Quarterly payments self-employed people (and others without withholding) "
                 "make directly to the IRS. Due: April 15, June 15, Sept 15, Jan 15. "
                 "Underpayment can trigger a penalty.",
        "irs_ref": "IRC §6654"
    },

    # ── Special ────────────────────────────────────────────────────────────────
    "amt": {
        "term": "Alternative Minimum Tax (AMT)",
        "plain": "A parallel tax system with fewer deductions and a flat rate (26%/28%). "
                 "You calculate tax both ways and pay whichever is higher. "
                 "Designed to ensure high earners pay some minimum tax. Has an exemption "
                 "that phases out at higher incomes.",
        "irs_ref": "IRC §§55-59"
    },
    "fica": {
        "term": "FICA (Social Security + Medicare)",
        "plain": "Payroll taxes: Social Security (6.2% up to wage base) + Medicare (1.45%). "
                 "Employees pay half; employers match. Self-employed pay both halves (15.3%) "
                 "but can deduct half above-the-line.",
        "irs_ref": "IRC §§3101-3111"
    },
    "se_tax": {
        "term": "Self-Employment Tax",
        "plain": "Self-employed people pay 15.3% (SS + Medicare) on net business income "
                 "up to the SS wage base, then 2.9% above. You can deduct half of SE tax "
                 "from AGI.",
        "irs_ref": "IRC §1401"
    },
    "tcja": {
        "term": "Tax Cuts and Jobs Act (TCJA)",
        "plain": "Major 2017 tax law that doubled the standard deduction, lowered brackets, "
                 "capped SALT at $10,000, created the QBI deduction, and more. "
                 "Many individual provisions expire after December 31, 2025.",
        "irs_ref": "Pub. L. 115-97 (2017)"
    },
    "depreciation": {
        "term": "Depreciation",
        "plain": "Writing off the cost of a business asset over its useful life. "
                 "Bonus depreciation and Section 179 allow faster write-offs. "
                 "Important for self-employed with equipment, vehicles, or rental property.",
        "irs_ref": "IRC §§167, 168, 179"
    },
    "hsa": {
        "term": "Health Savings Account (HSA)",
        "plain": "Triple tax advantage: contributions are deductible, growth is tax-free, "
                 "withdrawals for medical expenses are tax-free. Must have a high-deductible "
                 "health plan (HDHP). Unused funds roll over — no 'use it or lose it'.",
        "irs_ref": "IRC §223"
    },
}
