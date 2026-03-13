#!/usr/bin/env python3
"""
Package Telegram Bot Manager Skill for ClawHub
"""

import os
import sys
import json
import zipfile
from pathlib import Path


def validate_skill(skill_path: Path) -> bool:
    """Validate skill structure and content"""
    print("🔍 Validating skill...")
    
    # Check SKILL.md exists
    skill_md = skill_path / "SKILL.md"
    if not skill_md.exists():
        print("❌ SKILL.md not found")
        return False
    
    # Read and parse SKILL.md
    with open(skill_md, 'r') as f:
        content = f.read()
    
    # Parse frontmatter
    if content.startswith('---'):
        parts = content.split('---', 2)
        if len(parts) >= 3:
            try:
                # Simple YAML parser for basic key-value pairs
                frontmatter_text = parts[1].strip()
                frontmatter = {}
                
                for line in frontmatter_text.split('\n'):
                    line = line.strip()
                    if ':' in line:
                        key, value = line.split(':', 1)
                        key = key.strip()
                        value = value.strip().strip('"').strip("'")
                        frontmatter[key] = value
                
                # Check required fields
                if 'name' not in frontmatter:
                    print("❌ Missing 'name' in frontmatter")
                    return False
                
                if 'description' not in frontmatter:
                    print("❌ Missing 'description' in frontmatter")
                    return False
                
                # Validate name format
                name = frontmatter['name']
                if not name.replace('-', '').replace('_', '').isalnum():
                    print(f"❌ Invalid name format: {name}")
                    return False
                
                print(f"✅ Skill name: {name}")
                print(f"✅ Description: {frontmatter['description'][:50]}...")
                
            except Exception as e:
                print(f"❌ Invalid frontmatter: {e}")
                return False
        else:
            print("❌ Invalid SKILL.md format (missing frontmatter)")
            return False
    else:
        print("❌ SKILL.md missing frontmatter")
        return False
    
    # Check resource directories
    resources = ['scripts', 'references', 'assets']
    for resource in resources:
        resource_dir = skill_path / resource
        if resource_dir.exists():
            files = list(resource_dir.iterdir())
            if files:
                print(f"✅ {resource}/: {len(files)} file(s)")
            else:
                print(f"⚠️  {resource}/ is empty")
    
    return True


def package_skill(skill_path: Path, output_dir: Path = None) -> bool:
    """Package skill into .skill file"""
    print(f"\n📦 Packaging skill...")
    
    # Get skill name from frontmatter
    skill_md = skill_path / "SKILL.md"
    with open(skill_md, 'r') as f:
        content = f.read()
    
    parts = content.split('---', 2)
    # Simple YAML parser
    frontmatter_text = parts[1].strip()
    frontmatter = {}
    for line in frontmatter_text.split('\n'):
        line = line.strip()
        if ':' in line:
            key, value = line.split(':', 1)
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            frontmatter[key] = value
    skill_name = frontmatter['name']
    
    # Create output directory if needed
    if output_dir:
        output_dir.mkdir(parents=True, exist_ok=True)
    else:
        output_dir = skill_path.parent
    
    # Create .skill file (zip format)
    skill_file = output_dir / f"{skill_name}.skill"
    
    with zipfile.ZipFile(skill_file, 'w', zipfile.ZIP_DEFLATED) as zipf:
        # Add SKILL.md
        zipf.write(skill_md, 'SKILL.md')
        
        # Add resource directories
        for resource in ['scripts', 'references', 'assets']:
            resource_dir = skill_path / resource
            if resource_dir.exists():
                for file_path in resource_dir.rglob('*'):
                    if file_path.is_file():
                        arcname = file_path.relative_to(skill_path)
                        zipf.write(file_path, arcname)
    
    print(f"✅ Created: {skill_file}")
    print(f"   Size: {skill_file.stat().st_size:,} bytes")
    
    return True


def main():
    """Main entry point"""
    if len(sys.argv) < 2:
        print("Usage: python3 package_skill.py <skill-path> [output-dir]")
        print("Example: python3 package_skill.py ./telegram-bot-manager ./dist")
        sys.exit(1)
    
    skill_path = Path(sys.argv[1])
    
    if not skill_path.exists():
        print(f"❌ Skill path does not exist: {skill_path}")
        sys.exit(1)
    
    output_dir = None
    if len(sys.argv) > 2:
        output_dir = Path(sys.argv[2])
    
    # Validate
    if not validate_skill(skill_path):
        print("\n❌ Validation failed")
        sys.exit(1)
    
    # Package
    if not package_skill(skill_path, output_dir):
        print("\n❌ Packaging failed")
        sys.exit(1)
    
    print("\n🎉 Skill packaged successfully!")
    print("   Upload to ClawHub: clawhub publish <path-to-skill>")


if __name__ == "__main__":
    main()
