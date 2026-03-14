import json

def try_fix_json(content: str) -> str:
    content = content.strip()
    try:
        json.loads(content)
        return content
    except json.JSONDecodeError as e:
        msg = str(e)
        if "Unterminated string" in msg or "Expecting" in msg or "Extra data" in msg:
            # Simple heuristic: count braces and brackets
            open_braces = content.count('{')
            close_braces = content.count('}')
            open_brackets = content.count('[')
            close_brackets = content.count(']')
            
            # If it's a string that got cut off, close the quote
            if content.count('"') % 2 != 0:
                content += '"'
            
            # Close arrays and objects
            while open_brackets > close_brackets or open_braces > close_braces:
                # Add what's needed based on the last unclosed structure
                # This is a very basic fix, let's just attempt appending reasonable closings
                if open_braces > close_braces:
                    content += '}'
                    close_braces += 1
                elif open_brackets > close_brackets:
                    content += ']'
                    close_brackets += 1
                    
            try:
                json.loads(content)
                return content
            except json.JSONDecodeError:
                pass
        raise e
        
print("OK")
