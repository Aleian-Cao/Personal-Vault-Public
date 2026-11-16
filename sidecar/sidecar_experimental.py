"""Entry point of the EXPERIMENTAL sidecar build only: allows Qwen (still needs PVAULT_QWEN=1). Never shipped in release."""
import sidecar_server

sidecar_server.QWEN_ALLOWED = True
sidecar_server.TEST_HOOKS = True  # QA hooks exist only in the experimental build

if __name__ == '__main__':
    sidecar_server.main()
