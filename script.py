import os
import subprocess
import traceback
import yaml
import json
from flask import Flask, jsonify, send_file, request
from flask_cors import CORS
import logging
import google.generativeai as genai
import werkzeug
from dotenv import load_dotenv
import uuid
from ruamel.yaml import YAML
# Load environment variables
load_dotenv()

# Configure Gemini API
GEMINI_API_KEY = os.getenv('GEMINI_API_KEY')
genai.configure(api_key=GEMINI_API_KEY)

app = Flask(__name__)
CORS(app)

# Configure logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

# Define paths
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
INPUT_FOLDER = os.path.join(BASE_DIR, 'temp', 'input')
OUTPUT_FOLDER = os.path.join(BASE_DIR, 'temp', 'output')
BASE_YAML_PATH = os.path.join(BASE_DIR, 'resume.yaml')

# Ensure input and output folders exist
os.makedirs(INPUT_FOLDER, exist_ok=True)
os.makedirs(OUTPUT_FOLDER, exist_ok=True)

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
        
        if json_resume["basics"].get("summary"):
            sections["summary"] = [json_resume["basics"]["summary"]]
        
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
        
        if json_resume.get("projects"):
            sections["projects"] = [
                {
                    "name": proj["name"],
                    "date": proj.get("startDate", ""),
                    "highlights": [proj.get("description", "")]
                }
                for proj in json_resume["projects"]
            ]
        
        if json_resume.get("skills"):
            sections["technologies"] = [
                {
                    "label": skill["name"],
                    "details": ", ".join(skill["keywords"])
                }
                for skill in json_resume["skills"]
            ]
        
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

def enhance_resume_with_gemini(yaml_content):
    try:
        model = genai.GenerativeModel('gemini-pro')
        
        enhancement_prompt = f"""
        You are a professional resume enhancement AI. Review the following resume YAML and provide suggestions to:
        1. Improve language and descriptions
        2. Highlight key achievements more effectively
        3. Use action-oriented and impactful language
        4. Ensure clarity and conciseness
        5. Align descriptions with industry best practices

        Original Resume YAML:
        {yaml_content}

        Please return the enhanced YAML, maintaining the exact same structure. Focus on making the resume more compelling and professional.
        """
        
        response = model.generate_content(enhancement_prompt)
        
        enhanced_yaml = response.text.strip()
        
        try:
            yaml.safe_load(enhanced_yaml)
        except yaml.YAMLError:
            logger.warning("Gemini-generated YAML is invalid. Falling back to original.")
            return yaml_content
        
        return enhanced_yaml
    
    except Exception as e:
        logger.error(f"Gemini enhancement failed: {e}")
        return yaml_content
    
def replace_bullet_in_yaml(file_path, new_bullet="•"):
    """
    Replaces the `design.highlights.bullet` value in a YAML file with a new bullet character.
    
    Args:
        file_path (str): Path to the YAML file.
        new_bullet (str): The new bullet character to use (default is "•").
    
    Returns:
        bool: True if the replacement was successful, False otherwise.
    """
    try:
        yaml = YAML()
        with open(file_path, 'r', encoding='utf-8') as file:
            data = yaml.load(file)

        # Navigate to the `design.highlights.bullet` field
        if 'design' in data and 'highlights' in data['design']:
            data['design']['highlights']['bullet'] = new_bullet
        else:
            print("The specified path `design.highlights.bullet` does not exist in the YAML file.")
            return False

        # Save the modified YAML back to the file
        with open(file_path, 'w', encoding='utf-8') as file:
            yaml.dump(data, file)
        
        print(f"`design.highlights.bullet` successfully updated to '{new_bullet}'.")
        return True
    except Exception as e:
        print(f"An error occurred while processing the YAML file: {e}")
        return False
    
def generate_resume_pdf(json_file_path):
    try:
        # Read JSON file
        with open(json_file_path, 'r') as f:
            json_data = json.load(f)
        
        # Convert JSON to YAML
        converter = JSONResumeConverter(json_data)
        new_cv_yaml = converter.convert()
        
        # Enhance YAML with Gemini AI
        enhanced_cv_yaml = enhance_resume_with_gemini(new_cv_yaml)
        
        # Generate output filenames based on input filename
        input_filename = os.path.splitext(os.path.basename(json_file_path))[0]
        pdf_path = os.path.join(OUTPUT_FOLDER, f'{input_filename}_resume.pdf')
        yaml_path = os.path.join(OUTPUT_FOLDER, f'{input_filename}_resume.yaml')
        
        # Load base YAML design
        with open(BASE_YAML_PATH, 'r') as f:
            base_yaml = yaml.safe_load(f)
        
        # Update CV section with enhanced YAML
        new_cv_data = yaml.safe_load(enhanced_cv_yaml)
        base_yaml['cv'] = new_cv_data['cv']
        
        # Write merged YAML
        with open(yaml_path, 'w') as f:
            yaml.dump(base_yaml, f, default_flow_style=False)
        print(yaml_path)
        replace_bullet_in_yaml(yaml_path)
        # Run rendercv directly to output in the output folder
        result = subprocess.run(
            ['rendercv', 'render', yaml_path, '-o', pdf_path],
            capture_output=True,
            text=True,
            check=True,
            env=os.environ.copy(),
            cwd=OUTPUT_FOLDER
        )
        
        logger.info(f"PDF generated successfully at {pdf_path}")
        return pdf_path
    
    except Exception as e:
        logger.error(f"PDF generation failed: {e}")
        logger.error(traceback.format_exc())
        raise

def process_json_files():
    """Process all JSON files in the input folder"""
    processed_count = 0
    for filename in os.listdir(INPUT_FOLDER):
        if filename.endswith('.json'):
            try:
                input_path = os.path.join(INPUT_FOLDER, filename)
                output_pdf = generate_resume_pdf(input_path)
                processed_count += 1
                logger.info(f"Processed {filename}, PDF saved at {output_pdf}")
            except Exception as e:
                logger.error(f"Failed to process {filename}: {e}")
    
    logger.info(f"Total files processed: {processed_count}")

@app.route('/upload', methods=['POST'])
def upload_json():
    """
    Endpoint to upload JSON resume via request body
    """
    # Check if request body is JSON
    if not request.is_json:
        return jsonify({"error": "Request must be JSON"}), 400
    
    try:
        # Get JSON data from request
        json_data = request.get_json()
        
        # Validate JSON structure (basic check)
        if not json_data or 'basics' not in json_data:
            return jsonify({"error": "Invalid JSON resume format"}), 400
        
        # Generate unique filename
        filename = f"{uuid.uuid4()}_resume.json"
        file_path = os.path.join(INPUT_FOLDER, filename)
        
        # Save JSON to file
        with open(file_path, 'w') as f:
            json.dump(json_data, f, indent=2)
        
        logger.info(f"JSON file saved: {file_path}")
        
        # Generate PDF
        pdf_path = generate_resume_pdf(file_path)
        
        return jsonify({
            "message": "Resume processed successfully",
            "pdf_path": pdf_path,
            "json_filename": filename
        }), 200
    
    except Exception as e:
        logger.error(f"Error processing JSON: {e}")
        return jsonify({"error": str(e)}), 500

if __name__ == '__main__':
    app.run(debug=True, port=5000)