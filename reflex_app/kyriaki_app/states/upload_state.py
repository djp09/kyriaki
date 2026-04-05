import reflex as rx


class UploadState(rx.State):
    uploading: bool = False
    upload_error: str = ""
    document_type: str = ""
    confidence: float = 0.0
    extracted: dict[str, str] = {}
    extraction_notes: str = ""
    confirm_step: bool = False
    confirm_age: str = ""
    confirm_sex: str = ""
    confirm_zip: str = ""
    confirm_travel: str = "50"
    file_name: str = ""
    file_size: str = ""

    def _reset_state(self):
        self.uploading = False
        self.upload_error = ""
        self.document_type = ""
        self.confidence = 0.0
        self.extracted = {}
        self.extraction_notes = ""
        self.confirm_step = False
        self.confirm_age = ""
        self.confirm_sex = ""
        self.confirm_zip = ""
        self.confirm_travel = "50"
        self.file_name = ""
        self.file_size = ""

    def _clear_results(self):
        self.document_type = ""
        self.confidence = 0.0
        self.extracted = {}
        self.extraction_notes = ""
        self.confirm_step = False
        self.confirm_age = ""
        self.confirm_sex = ""

    @rx.var
    def has_result(self) -> bool:
        return self.document_type != ""

    @rx.var
    def doc_type_label(self) -> str:
        labels = {
            "pathology_report": "Pathology Report",
            "treatment_summary": "Treatment Summary",
            "lab_results": "Lab Results",
            "radiology_report": "Radiology Report",
            "clinical_note": "Clinical Note",
            "other": "Medical Document",
        }
        return labels.get(self.document_type, "Document")

    @rx.var
    def confidence_pct(self) -> int:
        return int(self.confidence * 100)

    @rx.var
    def extracted_fields_count(self) -> int:
        return len([v for v in self.extracted.values() if v])

    @rx.event
    async def handle_upload(self, files: list[rx.UploadFile]):
        if not files:
            return
        file = files[0]
        self._clear_results()
        self.upload_error = ""
        self.file_name = file.filename or "document"
        self.uploading = True
        yield
        try:
            file_data = await file.read()
            size_bytes = len(file_data)
            if size_bytes > 10 * 1024 * 1024:
                self.uploading = False
                self.upload_error = f"File too large ({size_bytes / (1024*1024):.1f} MB). Maximum is 10MB."
                return
            if size_bytes < 1024:
                self.file_size = f"{size_bytes} B"
            elif size_bytes < 1024 * 1024:
                self.file_size = f"{size_bytes / 1024:.1f} KB"
            else:
                self.file_size = f"{size_bytes / (1024 * 1024):.1f} MB"
            from ..api_client import upload_document
            data = await upload_document(file_data, self.file_name)
            doc_type = data.get("document_type", "other")
            conf = data.get("confidence", 0.0)
            extracted_raw = data.get("extracted", {})
            flat: dict[str, str] = {}
            for k, v in extracted_raw.items():
                if isinstance(v, list):
                    flat[k] = ", ".join(str(i) for i in v)
                elif isinstance(v, dict):
                    for sk, sv in v.items():
                        flat[f"{k}_{sk}"] = str(sv) if sv is not None else ""
                elif v is not None:
                    flat[k] = str(v)
                else:
                    flat[k] = ""
            self.document_type = doc_type
            self.confidence = conf
            self.extracted = flat
            self.extraction_notes = data.get("extraction_notes", "")
            self.uploading = False
            age_val = flat.get("age", "")
            sex_val = flat.get("sex", "")
            if age_val:
                self.confirm_age = age_val
            if sex_val:
                self.confirm_sex = sex_val
        except Exception as e:
            self._clear_results()
            self.upload_error = str(e)
            self.uploading = False

    @rx.event
    def show_confirm(self):
        self.confirm_step = True

    @rx.event
    def set_confirm_age(self, val: str):
        self.confirm_age = val

    @rx.event
    def set_confirm_sex(self, val: str):
        self.confirm_sex = val

    @rx.event
    def set_confirm_zip(self, val: str):
        self.confirm_zip = val

    @rx.event
    def set_confirm_travel(self, val: str):
        self.confirm_travel = val

    def _build_patient_payload(self) -> dict:
        ext = self.extracted
        biomarkers_str = ext.get("biomarkers", "")
        biomarkers = [b.strip() for b in biomarkers_str.split(",") if b.strip()] if biomarkers_str else []
        treatments_str = ext.get("prior_treatments", "")
        treatments = [t.strip() for t in treatments_str.split(",") if t.strip()] if treatments_str else []
        conditions_str = ext.get("additional_conditions", "")
        conditions = [c.strip() for c in conditions_str.split(",") if c.strip()] if conditions_str else []
        key_labs: dict = {}
        for lab in ["wbc", "platelets", "hemoglobin", "creatinine"]:
            val = ext.get(f"key_labs_{lab}", "")
            if val:
                try:
                    key_labs[lab] = float(val)
                except ValueError:
                    pass
        lines = 0
        lines_str = ext.get("lines_of_therapy", "")
        if lines_str:
            try:
                lines = int(lines_str)
            except ValueError:
                pass
        ecog = None
        ecog_str = ext.get("ecog_score", "")
        if ecog_str:
            try:
                ecog = int(ecog_str)
            except ValueError:
                pass
        age = 0
        if self.confirm_age:
            try:
                age = int(self.confirm_age)
            except ValueError:
                pass
        travel = 50
        if self.confirm_travel:
            try:
                travel = int(self.confirm_travel)
            except ValueError:
                pass
        payload: dict = {
            "cancer_type": ext.get("cancer_type", ""),
            "cancer_stage": ext.get("cancer_stage", ""),
            "biomarkers": biomarkers,
            "prior_treatments": treatments,
            "lines_of_therapy": lines,
            "age": age,
            "sex": self.confirm_sex or ext.get("sex", "male"),
            "location_zip": self.confirm_zip,
            "willing_to_travel_miles": travel,
            "additional_conditions": conditions,
            "additional_notes": ext.get("additional_notes", ""),
        }
        if ecog is not None:
            payload["ecog_score"] = ecog
        if key_labs:
            payload["key_labs"] = key_labs
        return payload

    @rx.event
    async def confirm_submit(self):
        if not self.confirm_zip or not self.confirm_age or not self.confirm_sex:
            self.upload_error = "Please fill in all required fields."
            return
        patient = self._build_patient_payload()
        from .navigation_state import NavigationState
        nav = await self.get_state(NavigationState)
        nav.previous_view = "upload"
        from .match_state import MatchState
        yield MatchState.start_match(patient)

    @rx.event
    async def skip_to_intake(self):
        from .navigation_state import NavigationState
        nav = await self.get_state(NavigationState)
        nav.view = "intake"

    @rx.event
    def clear_upload(self):
        self._reset_state()

    @rx.event
    async def prefill_and_go_intake(self):
        from .intake_state import IntakeState
        intake = await self.get_state(IntakeState)
        intake._apply_prefill(self.extracted)
        from .navigation_state import NavigationState
        nav = await self.get_state(NavigationState)
        nav.view = "intake"
