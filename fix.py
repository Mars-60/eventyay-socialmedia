
with open("tests/test_tasks.py", "r", encoding="utf-8") as f:
    c = f.read()
c = c.replace("entity_id=\"cfp_2\"", "entity_id=\"schedule\"")
c = c.replace("post_type=\"cfp\",\n            entity_id=\"schedule\"", "post_type=\"schedule\",\n            entity_id=\"schedule\"")
c = c.replace("entity_id=\"cfp_3\"", "entity_id=\"ticket_123\"")
c = c.replace("post_type=\"cfp\",\n            entity_id=\"ticket_123\"", "post_type=\"ticket\",\n            entity_id=\"ticket_123\"")
c = c.replace("entity_id=\"cfp_4\"", "entity_id=\"speaker_1_2\"")
c = c.replace("post_type=\"cfp\",\n            entity_id=\"speaker_1_2\"", "post_type=\"speaker\",\n            entity_id=\"speaker_1_2\"")
c = c.replace("entity_id=\"cfp_5\"", "entity_id=\"session_1\"")
c = c.replace("post_type=\"cfp\",\n            entity_id=\"session_1\"", "post_type=\"session\",\n            entity_id=\"session_1\"")
c = c.replace("entity_id=\"cfp_6\"", "entity_id=\"cfp\"")
with open("tests/test_tasks.py", "w", encoding="utf-8") as f:
    f.write(c)

