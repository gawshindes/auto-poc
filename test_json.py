import json

fcontent = """
[\n  {\n    "id": "c001",\n    "name": "Elite Electrical Solutions",\n    "trade": "electrical",\n    "rating": 4.8,\n    "email": "quotes@eliteelectric.com",\n    "response_time": 3,\n    "preferred": true,\n    "recent_quotes": 12,\n    "typical_timeline": 10\n  },\n  {\n    "id": "c029",\n    "name": "Guardian Roofing Systems",\n    "trade": "roofing",\n    "rating": 4.7,\n    "email": "bids@guardianroofing.com",\n    "response_time": 4,\n    "preferred": true,\n    "recent_
"""

try:
    json.loads(fcontent)
except json.JSONDecodeError as base_e:
    fixed = fcontent.strip()
    unmasked = fixed.replace('\\"', '')
    if unmasked.count('"') % 2 != 0:
        fixed += '"'
        
    open_braces = fixed.count('{')
    close_braces = fixed.count('}')
    open_brackets = fixed.count('[')
    close_brackets = fixed.count(']')
    
    while open_brackets > close_brackets or open_braces > close_braces:
        if open_braces > close_braces:
            fixed += '}'
            close_braces += 1
        else:
            fixed += ']'
            close_brackets += 1
    try:
        json.loads(fixed)
        print("Success! Fixed JSON:", fixed[-40:])
    except json.JSONDecodeError as e:
        print("Still failing:", e)
