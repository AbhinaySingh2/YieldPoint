with open('agent.py', 'r', encoding='utf-8') as f:
    lines = f.readlines()

new_lines = []
in_transcription = False
for line in lines:
    if line.strip().startswith('def _on_transcription(ev) -> None:'):
        in_transcription = True
        new_lines.append(line)
        new_lines.append("        text = getattr(ev, 'transcript', getattr(ev, 'text', str(ev)))\n")
        new_lines.append("        is_final = getattr(ev, 'is_final', getattr(ev, 'final', False))\n")
        new_lines.append("        logger.info('[STT] final=%s %s', is_final, text)\n")
        new_lines.append("        import uuid\n")
        new_lines.append("        segment = rtc.TranscriptionSegment(\n")
        new_lines.append("            id=getattr(ev, 'item_id', getattr(ev, 'id', str(uuid.uuid4()))),\n")
        new_lines.append("            text=text,\n")
        new_lines.append("            start_time=0,\n")
        new_lines.append("            end_time=0,\n")
        new_lines.append("            language=getattr(ev, 'language', 'en') or 'en',\n")
        new_lines.append("            final=bool(is_final),\n")
        new_lines.append("        )\n")
        new_lines.append("        t = rtc.Transcription(\n")
        new_lines.append("            participant_identity=participant.identity,\n")
        new_lines.append("            segments=[segment],\n")
        new_lines.append("        )\n")
        new_lines.append("        ctx.room.local_participant.publish_transcription(t)\n")
        new_lines.append("        if is_final:\n")
        new_lines.append("            pass\n")
        continue
    
    if in_transcription:
        if line.strip().startswith('@session.on'):
            in_transcription = False
            new_lines.append(line)
    else:
        new_lines.append(line)

with open('agent.py', 'w', encoding='utf-8') as f:
    f.writelines(new_lines)
