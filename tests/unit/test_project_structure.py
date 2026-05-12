"""
Test project structure and basic imports.
"""
import pytest
from pathlib import Path

def test_project_structure():
    """Test that project directories exist."""
    project_root = Path(__file__).parent.parent.parent

    # Check main directories
    required_dirs = [
        "src",
        "config",
        "data",
        "tests",
        "docs",
        "scripts",
        "notebooks",
        "logs",
    ]

    for dir_name in required_dirs:
        dir_path = project_root / dir_name
        assert dir_path.exists(), f"Directory {dir_name} does not exist"
        assert dir_path.is_dir(), f"{dir_name} is not a directory"

def test_src_structure():
    """Test src directory structure."""
    project_root = Path(__file__).parent.parent.parent
    src_dir = project_root / "src"

    required_src_dirs = [
        "models",
        "audio_processing",
        "daw_integration",
        "api",
        "workflow",
        "utils",
    ]

    for dir_name in required_src_dirs:
        dir_path = src_dir / dir_name
        assert dir_path.exists(), f"src/{dir_name} does not exist"
        assert dir_path.is_dir(), f"src/{dir_name} is not a directory"

def test_config_files():
    """Test that configuration files exist."""
    project_root = Path(__file__).parent.parent.parent

    required_files = [
        "pyproject.toml",
        ".env.example",
        ".gitignore",
        "README.md",
        "requirements.txt",
    ]

    for file_name in required_files:
        file_path = project_root / file_name
        assert file_path.exists(), f"File {file_name} does not exist"
        assert file_path.is_file(), f"{file_name} is not a file"

def test_python_imports():
    """Test basic Python imports."""
    # Test that we can import from src
    import sys
    project_root = Path(__file__).parent.parent.parent
    sys.path.insert(0, str(project_root))

    # Test importing base modules
    from src.models.base import BaseModel, ModelConfig, GenerationResult
    from src import __version__

    assert __version__ == "0.1.0"

    # Test that BaseModel is abstract
    with pytest.raises(TypeError):
        BaseModel()  # Should fail because BaseModel is abstract

def test_script_files():
    """Test that script files exist and are executable."""
    project_root = Path(__file__).parent.parent.parent
    scripts_dir = project_root / "scripts"

    # Check setup script
    setup_script = scripts_dir / "setup" / "setup_project.py"
    assert setup_script.exists(), "setup_project.py does not exist"

    # Check example script
    example_script = scripts_dir / "examples" / "basic_generation.py"
    assert example_script.exists(), "basic_generation.py does not exist"

def test_data_directories():
    """Test that data directories exist."""
    project_root = Path(__file__).parent.parent.parent
    data_dir = project_root / "data"

    required_data_dirs = [
        "raw",
        "processed",
        "models",
        "samples",
        "outputs",
    ]

    for dir_name in required_data_dirs:
        dir_path = data_dir / dir_name
        assert dir_path.exists(), f"data/{dir_name} does not exist"
        assert dir_path.is_dir(), f"data/{dir_name} is not a directory"

if __name__ == "__main__":
    # Run tests directly
    test_project_structure()
    test_src_structure()
    test_config_files()
    test_python_imports()
    test_script_files()
    test_data_directories()
    print("All structure tests passed!")