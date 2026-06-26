#!/usr/bin/env python3
from pathlib import Path
text = Path('ui/views/tools_view.py').read_text(encoding='utf-8')
assert 'self.keep_source_mode = True' in text
assert 'self.keep_source_checkbox = ft.Checkbox(' in text
assert r'\u4fdd\u7559\u6e90\u76ee\u5f55' in text
print('OK default migration mode is keep-source')
