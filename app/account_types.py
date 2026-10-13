"""Descriptions for the five account types used by this general ledger."""

ACCOUNT_TYPES = {
    "ASSET": {
        "label": "資產",
        "meaning": "企業控制、可帶來經濟效益的資源。",
        "examples": "現金、銀行存款、設備",
        "normal_side": "借方",
        "statement": "資產負債表",
    },
    "LIABILITY": {
        "label": "負債",
        "meaning": "企業因過去事項而有的現時付款或移轉資源義務。",
        "examples": "應付帳款、借款",
        "normal_side": "貸方",
        "statement": "資產負債表",
    },
    "EQUITY": {
        "label": "權益",
        "meaning": "資產扣除負債後，歸屬於業主的剩餘權益。",
        "examples": "投入資本、保留盈餘",
        "normal_side": "貸方",
        "statement": "資產負債表",
    },
    "REVENUE": {
        "label": "收入",
        "meaning": "銷貨或提供服務等帶來的收入，會增加本期損益。",
        "examples": "銷貨收入、服務收入",
        "normal_side": "貸方",
        "statement": "損益表",
    },
    "EXPENSE": {
        "label": "費用",
        "meaning": "營運時耗用的資源或發生的成本，會減少本期損益。",
        "examples": "薪資費用、租金費用",
        "normal_side": "借方",
        "statement": "損益表",
    },
}
