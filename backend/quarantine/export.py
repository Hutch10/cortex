from services.audit import pulse_audit
from pathlib import Path

class ExportService:
    def generate_obsidian_bundle(self) -> str:
        """Generate a single consolidated Markdown file for Obsidian import."""
        entries = pulse_audit.get_all_entries()
        
        md_content = "# TerraPulse Second Brain: Resonance Ledger\n"
        md_content += f"**Cortex Identity:** `{entries[0]['cortex_id'] if entries else 'N/A'}`\n\n"
        
        for entry in entries:
            md_content += f"## Pulse Entry: {entry['timestamp']}\n"
            md_content += "---\n"
            md_content += f"**Kp Index:** {entry['kp_index']}\n"
            md_content += f"**Seismic Events:** {entry['seismic_count']}\n"
            md_content += f"**Integrity Hash:** `{entry['hash']}`\n"
            md_content += f"**Seal:** `{entry['signature']}`\n"
            md_content += "---\n\n"
            md_content += f"{entry['payload']}\n\n"
            md_content += "--- \n\n"
            
        return md_content

export_service = ExportService()
