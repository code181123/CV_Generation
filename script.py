import os
import subprocess
import traceback
import yaml
from flask import Flask, request, jsonify, send_file
from flask_cors import CORS
import logging

app = Flask(__name__)
CORS(app)

# Configure logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

BASE_YAML_PATH = 'resume.yaml'

class JSONResumeConverter:
    def __init__(self, json_resume):
        basics = json_resume["basics"]
        self.render_cv = {
            "cv": {
                "name": basics["name"],
                "location": self._format_location(basics.get("location")),
                "email": basics["email"],
                "phone": basics["phone"],
                "website": basics.get("url", ""),
                "social_networks": self._format_social_networks(basics.get("profiles", [])),
                "sections": self._build_sections(json_resume)
            }
        }

    def _format_location(self, location):
        return f"{location['city']}, {location['countryCode']}" if location else ""

    def _format_social_networks(self, profiles):
        networks = {
            "github": "GitHub",
            "linkedin": "LinkedIn",
            "default": "GitHub"
        }
        return [
            {
                "network": networks.get(profile.get("network", "").lower(), networks["default"]),
                "username": profile.get("username", "")
            }
            for profile in profiles
        ]

    def _build_sections(self, json_resume):
        sections = {}
        
        # Summary
        if json_resume["basics"].get("summary"):
            sections["summary"] = [json_resume["basics"]["summary"]]
        
        # Education
        if json_resume.get("education"):
            sections["education"] = [
                {
                    "institution": edu["institution"],
                    "area": edu["area"],
                    "degree": edu["studyType"],
                    "start_date": edu["startDate"],
                    "end_date": edu.get("endDate", "present"),
                    "highlights": edu.get("courses", [])
                }
                for edu in json_resume["education"]
            ]
        
        # Experience
        if json_resume.get("work"):
            sections["experience"] = [
                {
                    "company": job["name"],
                    "position": job["position"],
                    "location": job.get("location", ""),
                    "start_date": job["startDate"],
                    "end_date": job.get("endDate", "present"),
                    "highlights": job.get("highlights", [])
                }
                for job in json_resume["work"]
            ]
        
        # Publications
        if json_resume.get("publications"):
            sections["publications"] = [
                {
                    "title": pub["name"],
                    "authors": pub.get("authors", []),
                    "date": pub["releaseDate"],
                    "doi": pub.get("doi"),
                    "url": pub.get("url")
                }
                for pub in json_resume["publications"]
            ]
        
        # Projects
        if json_resume.get("projects"):
            sections["projects"] = [
                {
                    "name": proj["name"],
                    "date": proj.get("startDate", ""),
                    "highlights": [proj.get("description", "")]
                }
                for proj in json_resume["projects"]
            ]
        
        # Technologies
        if json_resume.get("skills"):
            sections["technologies"] = [
                {
                    "label": skill["name"],
                    "details": ", ".join(skill["keywords"])
                }
                for skill in json_resume["skills"]
            ]
        
        # Awards
        if json_resume.get("awards"):
            sections["awards"] = [
                {
                    "label": award["title"],
                    "details": award["awarder"]
                }
                for award in json_resume["awards"]
            ]
        
        return sections

    def convert(self):
        return yaml.dump(self.render_cv, sort_keys=False)

@app.route('/generate_pdf', methods=['POST'])
def generate_pdf():
    if not request.is_json:
        return jsonify({"error": "Request must be JSON"}), 400
    
    yaml_path = "yaml"
    pdf_path = "pdf"
    
    try:
        json_data = request.get_json()
        
        # Convert JSON to YAML
        converter = JSONResumeConverter(json_data)
        new_cv_yaml = converter.convert()
        
        # Create temporary files with absolute paths
        script_dir = os.path.dirname(os.path.abspath(__file__))
        yaml_path = os.path.join(script_dir, 'temp_resume.yaml')
        pdf_path = os.path.abspath(os.path.join(script_dir, 'resume.pdf'))
        
        # Comprehensive error checking for rendercv
        try:
            # Check if rendercv is installed
            rendercv_version = subprocess.run(
                ['which', 'rendercv'], 
                capture_output=True, 
                text=True, 
                check=True
            )
            logger.info(f"RenderCV path: {rendercv_version.stdout.strip()}")
        except subprocess.CalledProcessError:
            return jsonify({
                "error": "RenderCV is not installed",
                "details": "Please install RenderCV using 'pipx install rendercv'"
            }), 500
        
        # Load base YAML design
        with open(BASE_YAML_PATH, 'r') as f:
            base_yaml = yaml.safe_load(f)
        
        # Update CV section
        new_cv_data = yaml.safe_load(new_cv_yaml)
        base_yaml['cv'] = new_cv_data['cv']
        
        # Write merged YAML
        with open(yaml_path, 'w') as f:
            yaml.dump(base_yaml, f, default_flow_style=False)
        
        # Comprehensive logging of YAML contents
        logger.debug(f"Generated YAML contents:\n{open(yaml_path, 'r').read()}")
        
        # Run rendercv with comprehensive error handling
        try:
            result = subprocess.run(
                ['rendercv', 'render', yaml_path, '-o', pdf_path],
                capture_output=True,
                text=True,
                check=True,
                env=os.environ.copy()  # Ensure full environment is passed
            )
            logger.info("RenderCV stdout: %s", result.stdout)
            logger.info("RenderCV stderr: %s", result.stderr)
        except subprocess.CalledProcessError as e:
            logger.error("RenderCV error: %s", e)
            logger.error("Stdout: %s", e.stdout)
            logger.error("Stderr: %s", e.stderr)
            return jsonify({
                "error": "PDF generation failed",
                "stdout": e.stdout,
                "stderr": e.stderr
            }), 500
        
        # Verify PDF generation
        if not os.path.isfile(pdf_path):
            logger.error("PDF file was not created")
            return jsonify({
                "error": "PDF file was not created",
                "script_dir": script_dir,
                "script_dir_contents": os.listdir(script_dir),
                "yaml_path": yaml_path
            }), 500
        
        response = send_file(
            pdf_path,
            as_attachment=True,
            download_name='resume.pdf',
            mimetype='application/pdf'
        )
        return response
    
    except Exception as e:
        logger.error("Processing failed: %s", str(e))
        logger.error("Traceback: %s", traceback.format_exc())
        return jsonify({
            "error": "Processing failed",
            "details": str(e),
            "traceback": traceback.format_exc()
        }), 500
    
    finally:
        # Clean up temporary files
        try:
            if yaml_path and os.path.exists(yaml_path):
                os.unlink(yaml_path)
            if pdf_path and os.path.exists(pdf_path):
                os.unlink(pdf_path)
        except Exception as cleanup_error:
            logger.error("Cleanup error: %s", str(cleanup_error))

if __name__ == '__main__':
    app.run(debug=True)