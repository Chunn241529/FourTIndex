import os
import json
from unittest.mock import patch, mock_open
from src.mcp_server import detect_active_project

def test_detect_active_project():
    registry_data = {
        "FourTIndex": "D:/project/FourTIndex",
        "dynamic_monas": "d:/project/dynamic_monas"
    }
    
    # 1. Test exact match
    with patch("os.path.exists", return_value=True), \
         patch("builtins.open", mock_open(read_data=json.dumps(registry_data))), \
         patch("os.getcwd", return_value="d:/project/dynamic_monas"):
        assert detect_active_project() == "dynamic_monas"
        
    # 2. Test ancestor directory match
    with patch("os.path.exists", return_value=True), \
         patch("builtins.open", mock_open(read_data=json.dumps(registry_data))), \
         patch("os.getcwd", return_value="d:/project/dynamic_monas/src/components"):
        assert detect_active_project() == "dynamic_monas"

    # 3. Test fallback to default project when no match
    with patch("os.path.exists", return_value=True), \
         patch("builtins.open", mock_open(read_data=json.dumps(registry_data))), \
         patch("os.getcwd", return_value="d:/project/unregistered"):
        # Should fallback to the project_name from config
        assert detect_active_project() == "FourTIndex"
