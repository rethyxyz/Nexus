import random
import string
username = ''.join(random.choice(string.ascii_letters + string.digits + "!@#$%^&*()_+-=[]{}|;:,.<>?") for _ in range(random.randint(8, 12)))
password = ''.join(random.choice(string.ascii_letters + string.digits + "!@#$%^&*()_+-=[]{}|;:,.<>?") for _ in range(random.randint(12, 16)))
print(f"\n{username}\n{password}")