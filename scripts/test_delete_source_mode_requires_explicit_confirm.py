#!/usr/bin/env python3
from pathlib import Path
text = Path('ui/views/tools_view.py').read_text(encoding='utf-8')
assert 'def require_delete_source_confirm' in text
assert 'self.delete_source_confirm_pending = True' in text
assert '??????' in text or '\u518d\u6b21\u70b9\u51fb\u6267\u884c' in text
print('OK delete-source mode requires explicit confirm')
