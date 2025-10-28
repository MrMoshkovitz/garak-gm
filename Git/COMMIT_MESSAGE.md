# Commit Message

```
Fix AttributeError in atkgen probe Turn object access

The atkgen probe was crashing with AttributeError when trying to access
.text directly on Turn objects. The Turn object structure uses .content
(Message object) which contains the .text attribute.

Updated line 208 in garak/probes/atkgen.py to use the correct access
pattern: turns[-1].content.text instead of turns[-1].text

This fixes crashes in the atkgen probe family and allows these probes
to run successfully.

Fixes #1444
```