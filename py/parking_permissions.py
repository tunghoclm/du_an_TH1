"""Danh mục phân quyền chi tiết theo cổng & vai trò cho Smart Parking (mô phỏng KiotViet)."""
import json

PERMISSION_GROUPS = [
    {
        'id': 'overview',
        'name': 'Tổng quan',
        'desc': 'Xem tổng quan doanh thu, lượt xe và trạng thái bãi',
        'singles': [
            {'key': 'dashboard.view', 'label': 'Xem tổng quan'},
        ],
        'sections': [],
    },
    {
        'id': 'parking',
        'name': 'Sơ đồ bãi đỗ xe',
        'desc': 'Khu vực, ô đỗ và bảo trì vị trí',
        'singles': [],
        'sections': [
            {
                'id': 'parking_areas',
                'name': 'Khu vực & Ô đỗ',
                'cols': {
                    'Xem': [{'key': 'parking.view', 'label': 'Khu vực & Ô đỗ'}],
                    'Tạo': [{'key': 'parking.create', 'label': 'Khu vực & Ô đỗ'}],
                    'Chỉnh sửa': [{'key': 'parking.edit', 'label': 'Khu vực & Ô đỗ'}],
                    'Xóa': [{'key': 'parking.delete', 'label': 'Khu vực & Ô đỗ'}],
                },
                'other': [
                    {'key': 'parking.import', 'label': 'Import'},
                    {'key': 'parking.export', 'label': 'Xuất file'},
                    {'key': 'parking.maintenance', 'label': 'Bảo trì ô đỗ'},
                ],
            },
        ],
    },
    {
        'id': 'pricing',
        'name': 'Bảng giá',
        'desc': 'Khung giờ, loại xe và đơn giá vé lượt / vé tháng',
        'singles': [],
        'sections': [
            {
                'id': 'pricing_rules',
                'name': 'Thiết lập bảng giá',
                'cols': {
                    'Xem': [{'key': 'pricing.view', 'label': 'Bảng giá'}],
                    'Tạo': [{'key': 'pricing.create', 'label': 'Bảng giá'}],
                    'Chỉnh sửa': [{'key': 'pricing.edit', 'label': 'Bảng giá'}],
                    'Xóa': [{'key': 'pricing.delete', 'label': 'Bảng giá'}],
                },
                'other': [
                    {'key': 'pricing.export', 'label': 'Xuất file'},
                ],
            },
        ],
    },
    {
        'id': 'gate',
        'name': 'Giám sát Cổng & Cabin',
        'desc': 'Làn xe vào / ra, nhận diện biển số và điều khiển barie',
        'singles': [],
        'sections': [
            {
                'id': 'gate_lanes',
                'name': 'Làn vào / ra & Cabin',
                'cols': {
                    'Xem': [{'key': 'gate.view', 'label': 'Màn hình cổng / Cabin'}],
                    'Tạo': [{'key': 'gate.entry', 'label': 'Xác nhận xe vào'}],
                    'Chỉnh sửa': [{'key': 'gate.exit', 'label': 'Xác nhận xe ra & thu phí'}],
                },
                'other': [
                    {'key': 'gate.barrier', 'label': 'Mở barie thủ công'},
                    {'key': 'gate.ocr', 'label': 'Chụp ảnh / Nhận diện biển số'},
                ],
            },
        ],
    },
    {
        'id': 'history_invoices',
        'name': 'Lịch sử & Hóa đơn',
        'desc': 'Nhật ký ra vào bãi, hóa đơn thu phí và in phiếu',
        'singles': [],
        'sections': [
            {
                'id': 'history_log',
                'name': 'Lịch sử vào / ra',
                'cols': {
                    'Xem': [{'key': 'history.view', 'label': 'Lịch sử vào / ra'}],
                },
                'other': [
                    {'key': 'history.export', 'label': 'Xuất file'},
                ],
            },
            {
                'id': 'invoices_list',
                'name': 'Hóa đơn thu phí',
                'cols': {
                    'Xem': [{'key': 'invoices.view', 'label': 'Hóa đơn'}],
                    'Chỉnh sửa': [{'key': 'invoices.edit', 'label': 'Hóa đơn'}],
                    'Hủy': [{'key': 'invoices.cancel', 'label': 'Hóa đơn'}],
                },
                'other': [
                    {'key': 'invoices.export', 'label': 'Xuất file'},
                    {'key': 'invoices.print', 'label': 'In phiếu thu'},
                ],
            },
        ],
    },
    {
        'id': 'customers',
        'name': 'Khách hàng & Vé tháng',
        'desc': 'Danh sách khách hàng, đăng ký xe và gia hạn vé tháng',
        'singles': [],
        'sections': [
            {
                'id': 'customer_list',
                'name': 'Danh sách khách hàng',
                'cols': {
                    'Xem': [{'key': 'customers.view', 'label': 'Khách hàng'}],
                    'Tạo': [{'key': 'customers.create', 'label': 'Khách hàng'}],
                    'Chỉnh sửa': [{'key': 'customers.edit', 'label': 'Khách hàng'}],
                    'Xóa': [{'key': 'customers.delete', 'label': 'Khách hàng'}],
                },
                'other': [
                    {'key': 'customers.export', 'label': 'Xuất file'},
                ],
            },
            {
                'id': 'monthly_tickets',
                'name': 'Vé tháng & Gia hạn',
                'cols': {
                    'Tạo': [{'key': 'monthly.create', 'label': 'Đăng ký vé tháng'}],
                    'Chỉnh sửa': [{'key': 'monthly.renew', 'label': 'Gia hạn vé tháng'}],
                    'Xóa': [{'key': 'monthly.delete', 'label': 'Hủy xe'}],
                },
                'other': [],
            },
        ],
    },
    {
        'id': 'staff',
        'name': 'Nhân viên',
        'desc': 'Thông tin nhân viên, chấm công và bảng tính lương',
        'singles': [],
        'sections': [
            {
                'id': 'staff_info',
                'name': 'Thông tin nhân viên',
                'cols': {
                    'Xem': [{'key': 'staff.view', 'label': 'Nhân viên'}, {'key': 'staff.salary_view', 'label': 'Mức lương'}],
                    'Tạo': [{'key': 'staff.create', 'label': 'Nhân viên'}],
                    'Chỉnh sửa': [{'key': 'staff.edit', 'label': 'Nhân viên'}],
                    'Xóa': [{'key': 'staff.delete', 'label': 'Nhân viên'}],
                },
                'other': [
                    {'key': 'staff.export', 'label': 'Xuất file nhân viên'},
                ],
            },
            {
                'id': 'staff_payroll',
                'name': 'Chấm công & Bảng lương',
                'cols': {
                    'Xem': [{'key': 'payroll.view', 'label': 'Bảng lương & Chấm công'}],
                    'Tạo': [{'key': 'payroll.create', 'label': 'Chấm công'}],
                    'Chỉnh sửa': [{'key': 'payroll.edit', 'label': 'Chốt lương'}],
                },
                'other': [
                    {'key': 'payroll.export', 'label': 'Xuất file bảng lương'},
                ],
            },
        ],
    },
    {
        'id': 'reports_settings',
        'name': 'Báo cáo & Cài đặt',
        'desc': 'Báo cáo doanh thu, thống kê và cài đặt hệ thống',
        'singles': [],
        'sections': [
            {
                'id': 'reports_stats',
                'name': 'Báo cáo & Thống kê',
                'cols': {
                    'Xem': [{'key': 'reports.view', 'label': 'Báo cáo & Thống kê'}],
                },
                'other': [
                    {'key': 'reports.export', 'label': 'Xuất file'},
                ],
            },
            {
                'id': 'system_settings',
                'name': 'Cài đặt hệ thống',
                'cols': {
                    'Xem': [{'key': 'settings.view', 'label': 'Cài đặt hệ thống'}],
                    'Chỉnh sửa': [{'key': 'settings.edit', 'label': 'Cài đặt cổng, VietQR, camera'}],
                },
                'other': [],
            },
        ],
    },
]

ALL_PERM_KEYS = []
for _g in PERMISSION_GROUPS:
    ALL_PERM_KEYS.extend(s['key'] for s in _g['singles'])
    for _sec in _g['sections']:
        for _items in _sec['cols'].values():
            ALL_PERM_KEYS.extend(i['key'] for i in _items)
        ALL_PERM_KEYS.extend(i['key'] for i in _sec['other'])

ROLE_PRESETS = {
    'Nhân viên vận hành': [
        'dashboard.view', 'parking.view', 'parking.maintenance', 'gate.view', 'gate.entry', 'gate.exit',
        'gate.barrier', 'gate.ocr', 'history.view', 'invoices.view', 'invoices.print',
        'customers.view', 'customers.create', 'customers.edit', 'monthly.create', 'monthly.renew',
    ],
    'Quản trị viên': list(ALL_PERM_KEYS),
}

OTHER_PERMISSIONS = [
    {
        'key': 'view_shared_info',
        'label': 'Xem thông tin chung của bảng giá, giao dịch, khách hàng',
        'hint': 'Cho phép xem dữ liệu bảng giá và thông tin cơ bản của khách hàng liên cổng.',
    },
    {
        'key': 'manage_other_staff_eod',
        'label': 'Xem, chỉnh sửa giao dịch và xem báo cáo cuối ngày của nhân viên khác',
        'hint': 'Cho phép kiểm tra doanh thu, hóa đơn và chốt ca của nhân viên khác trong cùng cổng.',
    },
]


def parse_permissions(raw_json, fallback_role='manager', fallback_branches=None):
    """Đọc permissions_json; nếu chưa thiết lập thì suy ra mặc định từ role + work_branch."""
    if raw_json:
        try:
            data = json.loads(raw_json)
            if isinstance(data, dict):
                gates = data.get('gates') if isinstance(data.get('gates'), dict) else {}
                other = data.get('other') if isinstance(data.get('other'), dict) else {}
                return {
                    'gates': gates,
                    'other': {
                        'view_shared_info': bool(other.get('view_shared_info')),
                        'manage_other_staff_eod': bool(other.get('manage_other_staff_eod')),
                    },
                }
        except (TypeError, ValueError):
            pass

    preset_name = 'Quản trị viên' if fallback_role == 'admin' else 'Nhân viên vận hành'
    default_perms = list(ROLE_PRESETS[preset_name])
    branches = fallback_branches or ['Cổng chính']
    return {
        'gates': {
            b: {'role_preset': preset_name, 'perms': list(default_perms)}
            for b in branches if b
        },
        'other': {
            'view_shared_info': fallback_role == 'admin',
            'manage_other_staff_eod': fallback_role == 'admin',
        },
    }


def sanitize_permissions(raw_json):
    """Chuẩn hóa JSON phân quyền gửi từ form; trả về (clean_obj, assigned_gates) hoặc (None, None)."""
    if not raw_json or not str(raw_json).strip():
        return None, None
    try:
        parsed = json.loads(raw_json)
    except (TypeError, ValueError):
        return None, None
    if not isinstance(parsed, dict):
        return None, None

    valid_keys = set(ALL_PERM_KEYS)
    clean_gates = {}
    for gname, entry in (parsed.get('gates') or {}).items():
        if not isinstance(entry, dict):
            continue
        preset = str(entry.get('role_preset') or '').strip()
        perms = [p for p in (entry.get('perms') or []) if p in valid_keys]
        if preset or perms:
            clean_gates[str(gname).strip()] = {'role_preset': preset, 'perms': sorted(set(perms))}
    other_in = parsed.get('other') or {}
    clean_obj = {
        'gates': clean_gates,
        'other': {
            'view_shared_info': bool(other_in.get('view_shared_info')),
            'manage_other_staff_eod': bool(other_in.get('manage_other_staff_eod')),
        },
    }
    return clean_obj, [g for g in clean_gates.keys() if g]


def summarize_permissions(perms_obj, all_gates):
    """Tạo dữ liệu tóm tắt cho tab Tài khoản & Phân quyền."""
    gates_map = perms_obj.get('gates') or {}
    gate_rows = []
    for gname in all_gates:
        entry = gates_map.get(gname)
        if entry and (entry.get('role_preset') or entry.get('perms')):
            gate_rows.append({
                'gate': gname,
                'role_preset': entry.get('role_preset') or 'Tùy chỉnh',
                'perm_count': len(entry.get('perms') or []),
            })
    return {
        'assigned_count': len(gate_rows),
        'total_gates': len(all_gates),
        'gate_rows': gate_rows,
        'other': perms_obj.get('other') or {'view_shared_info': False, 'manage_other_staff_eod': False},
    }


def user_permission_set(user_row, gate_name=None):
    """Tập quyền hiệu lực của user (toàn cục hoặc giới hạn theo 1 cổng)."""
    if user_row is None:
        return set()
    role = user_row['role']
    if role == 'user':
        return set()
    if user_row['username'] == 'admin' or (role == 'admin' and not user_row['permissions_json']):
        return set(ALL_PERM_KEYS)
    branches = [b.strip() for b in (user_row['work_branch'] or '').split(',') if b.strip()] or ['Cổng chính']
    perms_obj = parse_permissions(user_row['permissions_json'], role, branches)
    gates_map = perms_obj.get('gates') or {}
    if gate_name and gate_name != 'Tất cả các cổng':
        return set((gates_map.get(gate_name) or {}).get('perms') or [])
    result = set()
    for entry in gates_map.values():
        result.update(entry.get('perms') or [])
    return result


def user_has_permission(user_row, perm_key, gate_name=None):
    return perm_key in user_permission_set(user_row, gate_name=gate_name)


def user_allowed_gates(user_row):
    """Danh sách tên cổng user được phân quyền (None = không giới hạn, ví dụ admin gốc)."""
    if user_row is None or user_row['role'] == 'user':
        return []
    if user_row['username'] == 'admin' or (user_row['role'] == 'admin' and not user_row['permissions_json']):
        return None
    branches = [b.strip() for b in (user_row['work_branch'] or '').split(',') if b.strip()] or ['Cổng chính']
    perms_obj = parse_permissions(user_row['permissions_json'], user_row['role'], branches)
    gates_map = perms_obj.get('gates') or {}
    return [g for g, entry in gates_map.items() if g and (entry.get('role_preset') or entry.get('perms'))]

