import os
import time
import hashlib
import json
from tools import get_base_path

class ForensicLogger:
    """Handles compact, tokenized, and hashed forensic logging."""
    def __init__(self, log_filename="./forensic_audit.jsonl"):
        # Construct the absolute path to the logs folder right next to the exe/script
        base_dir = get_base_path()
        self.log_file = os.path.join(base_dir, "logs", log_filename)
        
        # Ensure the logs directory exists
        os.makedirs(os.path.dirname(self.log_file), exist_ok=True)

        # Token dictionary (Abstract Execution Traces)
        # Keeps the log file incredibly small by avoiding repeated text.
        self.tokens = {
            "START": "01",
            "EXIT": "02",
            "V_ADD": "10",
            "V_RM": "11",
            "C_NEW": "20",
            "C_SAVE": "21",
            "C_LOAD": "22",
            "M_UPD": "30",
            "COMP_ADD": "40",
            "COMP_RM": "41"
        }

    def get_file_hash(self, file_path):
        """Calculates SHA-256 hash to guarantee file integrity without storing data."""
        hasher = hashlib.sha256()
        try:
            with open(file_path, 'rb') as f:
                # Read in chunks to avoid blowing up memory with large videos
                for chunk in iter(lambda: f.read(4096), b""):
                    hasher.update(chunk)
            return hasher.hexdigest()
        except Exception:
            return None

    def log(self, event_type, data=None):
        """Appends a normalized, compact entry to the log."""
        token = self.tokens.get(event_type, "00")
        
        # Base entry: UTC Unix timestamp and event token
        entry = {
            "t": int(time.time()), 
            "e": token
        }
        
        if data:
            entry["d"] = data
            
        # Write compactly (no spaces) to save disk space
        with open(self.log_file, 'a') as f:
            f.write(json.dumps(entry, separators=(',', ':')) + "\n")

    def jsonl_to_human_readable(self, human_filename="./forensic_audit.txt"):
        """Reads the tokenized JSONL log file and exports a human-readable text report."""
        # Build the absolute path for the output text file
        base_dir = get_base_path()
        human_file = os.path.join(base_dir, "logs", human_filename)

        # Ensure the logs directory exists for the output text file
        os.makedirs(os.path.dirname(human_file), exist_ok=True)

        # Create a reverse lookup for tokens (e.g., "01" -> "START")
        reverse_tokens = {v: k for k, v in self.tokens.items()}
        
        descriptions = {
            "START": "Session started",
            "EXIT": "Session exited",
            "V_ADD": "Video added to session",
            "V_RM": "Video removed from session",
            "C_NEW": "New forensic case created",
            "C_SAVE": "Case data securely saved",
            "C_LOAD": "Existing case data loaded",
            "M_UPD": "Metadata updated",
            "COMP_ADD": "Comparison analysis added",
            "COMP_RM": "Comparison analysis removed"
        }

        try:
            with open(self.log_file, 'r') as infile, open(human_file, 'w') as outfile:
                outfile.write("=== FORENSIC AUDIT LOG REPORT ===\n\n")
                
                for line in infile:
                    if not line.strip():
                        continue
                    
                    try:
                        entry = json.loads(line)
                        timestamp = entry.get("t")
                        token = entry.get("e")
                        data = entry.get("d")
                        
                        readable_time = time.strftime('%Y-%m-%d %H:%M:%S UTC', time.gmtime(timestamp))
                        
                        event_name = reverse_tokens.get(token, "UNKNOWN")
                        action = descriptions.get(event_name, f"Unknown action taken (Token: {token})")
                        
                        log_sentence = f"[{readable_time}] {action}"
                        if data:
                            log_sentence += f" -> Details: {json.dumps(data)}"
                        
                        outfile.write(log_sentence + "\n")
                        
                    except json.JSONDecodeError:
                        outfile.write(f"[ERROR] Corrupted log entry detected and skipped.\n")
                        
            print(f"Success: Human-readable log successfully written to '{human_file}'")
            
        except FileNotFoundError:
            print(f"Error: The log file '{self.log_file}' does not exist yet.")