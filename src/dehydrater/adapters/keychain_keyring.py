import keyring
from keyring.errors import KeyringError, NoKeyringError, PasswordDeleteError

from dehydrater.credentials import KEYCHAIN_SERVICE, KeychainUnavailableError


class SystemKeychain:
    """通过 keyring 库访问系统钥匙串。

    Linux 上依赖 Secret Service（gnome-keyring、KWallet 等）；没有桌面环境时可能不可用，
    此时请改用环境变量或 .env。
    """

    def get(self, name: str) -> str | None:
        try:
            return keyring.get_password(KEYCHAIN_SERVICE, name)
        except KeyringError:
            return None

    def set(self, name: str, value: str) -> None:
        try:
            keyring.set_password(KEYCHAIN_SERVICE, name, value)
        except (NoKeyringError, KeyringError) as error:
            raise KeychainUnavailableError(f"系统钥匙串不可用：{error}") from error

    def delete(self, name: str) -> bool:
        try:
            keyring.delete_password(KEYCHAIN_SERVICE, name)
        except PasswordDeleteError:
            return False
        except KeyringError as error:
            raise KeychainUnavailableError(f"系统钥匙串不可用：{error}") from error
        return True
