import os
import pyinstaller_versionfile

# GitHub Actions exposes the tag name here (e.g., "v1.0.3")
raw_version = os.getenv("GITHUB_REF_NAME", "0.0.0")
# Clean up the "v" prefix if you use tags like v1.0.0
version_string = raw_version.lstrip('v')

# Windows file version details strictly require up to 4 dot-separated integers
segments = version_string.split('.')
while len(segments) < 4:
    segments.append('0')
four_part_version = ".".join(segments[:4])

pyinstaller_versionfile.create_versionfile(
    output_file="version_info.txt",
    version=four_part_version,
    company_name="Florian Kleint",
    file_description="A metadata-based analysis interface for correlating heterogeneous media data relating to major incidents.",
    internal_name="ConeTrace",
    legal_copyright="© 2026 Florian Kleint",
    original_filename="ConeTrace.exe",
    product_name="ConeTrace"
)
print(f"Successfully generated version_info.txt with version {four_part_version}")