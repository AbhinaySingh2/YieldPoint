with open('agent.py', 'r', encoding='utf-8') as f:
    text = f.read()

text = text.replace('≈', '~=')
text = text.replace('→', '->')
text = text.replace('endpointing={"min_delay": 0.2}', 'endpointing={"min_delay": 0.2, "max_delay": 0.3}')

with open('agent.py', 'w', encoding='utf-8') as f:
    f.write(text)
