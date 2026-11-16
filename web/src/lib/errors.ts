// Backend/core errors are English; map the known ones to consistent Vietnamese for the UI.
const MAP: [RegExp, string][] = [
  [/Cannot unlock/i, 'Mật khẩu không đúng hoặc file két sắt không hợp lệ.'],
  [/Vault file not found/i, 'Không tìm thấy file két sắt.'],
  [/Vault is locked/i, 'Két sắt đang khóa.'],
  [/Vault already exists/i, 'File này đã tồn tại. Chọn tên hoặc vị trí khác (ứng dụng không ghi đè).'],
  [/Cannot create vault inside application/i, 'Không thể lưu két sắt trong thư mục ứng dụng. Chọn vị trí khác.'],
  [/at least 12 characters/i, 'Mật khẩu chính cần tối thiểu 12 ký tự.'],
  [/Import rejected/i, 'File bị từ chối: sai định dạng, có trường không hợp lệ, thiếu dữ liệu hoặc trùng bản ghi. Không có gì được nhập.'],
  [/Duplicate account/i, 'Đã có tài khoản trùng (cùng Tài khoản và Tên đăng nhập).'],
  [/Sidecar|sidecar/i, 'Không kết nối được tiến trình lõi của ứng dụng.'],
];

export function errorText(e: unknown, fallback = 'Đã xảy ra lỗi.'): string {
  const raw = typeof e === 'string' ? e : (e as { message?: string })?.message ?? '';
  if (!raw) return fallback;
  return MAP.find(([re]) => re.test(raw))?.[1] ?? raw;
}

// "Locked" and "the sidecar died" are handled the same way: leave the vault view, ask the backend for the real state.
export const isLockedError = (e: unknown): boolean =>
  /locked|sidecar|empty response|invalid json|did not match the request/i.test(typeof e === 'string' ? e : (e as { message?: string })?.message ?? '');
