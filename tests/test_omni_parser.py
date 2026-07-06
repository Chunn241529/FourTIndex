import pytest
from src.config import Config
from src.indexer import Indexer

def test_typescript_parsing():
    config = Config()
    indexer = Indexer(config)
    
    ts_code = """
    class Vector3 {
        x: number;
        y: number;
        z: number;
        constructor(x: number, y: number, z: number) {
            this.x = x;
            this.y = y;
            this.z = z;
        }
        magnitude(): number {
            return Math.sqrt(this.x * this.x + this.y * this.y + this.z * this.z);
        }
    }
    """
    
    chunks = indexer.parse_with_tree_sitter(ts_code, "math.ts", "math.ts", "typescript")
    
    # Assert we have class outline and methods
    outlines = [c for c in chunks if c["chunk_type"] == "class_outline"]
    funcs = [c for c in chunks if c["chunk_type"] == "function"]
    
    assert len(outlines) == 1
    assert outlines[0]["symbol_name"] == "Vector3"
    
    # We should have magnitude and constructor
    assert len(funcs) == 2
    func_names = {f["symbol_name"] for f in funcs}
    assert "Vector3.constructor" in func_names
    assert "Vector3.magnitude" in func_names


def test_csharp_parsing():
    config = Config()
    indexer = Indexer(config)
    
    cs_code = """
    using UnityEngine;
    namespace Game {
        public class PlayerController : MonoBehaviour {
            public float speed = 5.0f;
            void Start() {
                Debug.Log("Player started");
            }
            void Update() {
                Move();
            }
            void Move() {
                // movement logic
            }
        }
    }
    """
    
    chunks = indexer.parse_with_tree_sitter(cs_code, "Player.cs", "Player.cs", "c_sharp")
    
    outlines = [c for c in chunks if c["chunk_type"] == "class_outline"]
    funcs = [c for c in chunks if c["chunk_type"] == "function"]
    
    assert len(outlines) == 1
    assert outlines[0]["symbol_name"] == "PlayerController"
    
    assert len(funcs) == 3
    func_names = {f["symbol_name"] for f in funcs}
    assert "PlayerController.Start" in func_names
    assert "PlayerController.Update" in func_names
    assert "PlayerController.Move" in func_names


def test_error_recovery_parsing():
    config = Config()
    indexer = Indexer(config)
    
    # Code with a syntax error in the middle (missing closing brace)
    ts_code_with_error = """
    class GoodClass {
        sayHello() {
            console.log("hello");
        }
    }
    
    class BadClass {
        sayBad() {
            console.log("bad"
        }
    }
    
    class AnotherGoodClass {
        sayYes() {
            console.log("yes");
        }
    }
    """
    
    # Parsing should run without throwing exceptions
    chunks = indexer.parse_with_tree_sitter(ts_code_with_error, "error.ts", "error.ts", "typescript")
    
    outlines = [c for c in chunks if c["chunk_type"] == "class_outline"]
    funcs = [c for c in chunks if c["chunk_type"] == "function"]
    
    # We should have GoodClass and AnotherGoodClass parsed successfully
    outline_names = {o["symbol_name"] for o in outlines}
    assert "GoodClass" in outline_names
    assert "AnotherGoodClass" in outline_names
    
    func_names = {f["symbol_name"] for f in funcs}
    assert "GoodClass.sayHello" in func_names
    assert "AnotherGoodClass.sayYes" in func_names
