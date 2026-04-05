import reflex as rx

CANCER_TYPES: list[str] = [
    "Non-Small Cell Lung Cancer",
    "Small Cell Lung Cancer",
    "Triple-Negative Breast Cancer",
    "HER2+ Breast Cancer",
    "Hormone Receptor+ Breast Cancer",
    "Colorectal Cancer",
    "Pancreatic Cancer",
    "Acute Lymphoblastic Leukemia",
    "Neuroblastoma",
    "Wilms Tumor",
    "Osteosarcoma",
    "Ewing Sarcoma",
    "Rhabdomyosarcoma",
]

STAGES: list[str] = [
    "Stage I",
    "Stage II",
    "Stage IIA",
    "Stage IIB",
    "Stage III",
    "Stage IIIA",
    "Stage IIIB",
    "Stage IV",
    "Stage IVA",
    "Stage IVB",
    "Recurrent",
    "Metastatic",
]


class IntakeState(rx.State):
    step: int = 0
    cancer_type: str = ""
    cancer_stage: str = ""
    biomarkers: str = ""
    prior_treatments: str = ""
    lines_of_therapy: int = 0
    age: str = ""
    sex: str = ""
    ecog_score: str = ""
    key_labs_wbc: str = ""
    key_labs_platelets: str = ""
    key_labs_hemoglobin: str = ""
    key_labs_creatinine: str = ""
    location_zip: str = ""
    willing_to_travel_miles: int = 50
    additional_conditions: str = ""
    additional_notes: str = ""
    errors: dict[str, str] = {}
    direction: int = 1
    cancer_types: list[str] = CANCER_TYPES
    stages: list[str] = STAGES
    step_indices: list[int] = [0, 1, 2, 3, 4]
    lines_options: list[str] = ["0", "1", "2", "3", "4", "5"]
    ecog_options: list[str] = ["", "0", "1", "2", "3", "4"]

    def _reset_state(self):
        self.step = 0
        self.cancer_type = ""
        self.cancer_stage = ""
        self.biomarkers = ""
        self.prior_treatments = ""
        self.lines_of_therapy = 0
        self.age = ""
        self.sex = ""
        self.ecog_score = ""
        self.key_labs_wbc = ""
        self.key_labs_platelets = ""
        self.key_labs_hemoglobin = ""
        self.key_labs_creatinine = ""
        self.location_zip = ""
        self.willing_to_travel_miles = 50
        self.additional_conditions = ""
        self.additional_notes = ""
        self.errors = {}
        self.direction = 1

    def _apply_prefill(self, data: dict):
        if data.get("cancer_type"):
            self.cancer_type = data["cancer_type"]
        if data.get("cancer_stage"):
            self.cancer_stage = data["cancer_stage"]
        if data.get("biomarkers"):
            self.biomarkers = data["biomarkers"]
        if data.get("prior_treatments"):
            self.prior_treatments = data["prior_treatments"]
        if data.get("lines_of_therapy"):
            try:
                self.lines_of_therapy = int(data["lines_of_therapy"])
            except ValueError:
                pass
        if data.get("age"):
            self.age = data["age"]
        if data.get("sex"):
            self.sex = data["sex"]
        if data.get("ecog_score"):
            self.ecog_score = data["ecog_score"]
        if data.get("additional_conditions"):
            self.additional_conditions = data["additional_conditions"]
        if data.get("additional_notes"):
            self.additional_notes = data["additional_notes"]
        for lab in ["wbc", "platelets", "hemoglobin", "creatinine"]:
            val = data.get(f"key_labs_{lab}", "")
            if val:
                setattr(self, f"key_labs_{lab}", val)

    def _validate_step(self) -> dict[str, str]:
        errs: dict[str, str] = {}
        if self.step == 0:
            if not self.cancer_type:
                errs["cancer_type"] = "Please select a cancer type."
            if not self.cancer_stage:
                errs["cancer_stage"] = "Please select a stage."
        elif self.step == 2:
            if not self.age:
                errs["age"] = "Age is required."
            else:
                try:
                    a = int(self.age)
                    if a < 0 or a > 120:
                        errs["age"] = "Enter a valid age (0-120)."
                except ValueError:
                    errs["age"] = "Enter a valid age (0-120)."
            if not self.sex:
                errs["sex"] = "Please select sex."
        elif self.step == 3:
            for lab_name, lab_field in [
                ("WBC", self.key_labs_wbc),
                ("Platelets", self.key_labs_platelets),
                ("Hemoglobin", self.key_labs_hemoglobin),
                ("Creatinine", self.key_labs_creatinine),
            ]:
                if lab_field:
                    try:
                        v = float(lab_field)
                        if v < 0:
                            errs[f"key_labs_{lab_name.lower()}"] = "Enter a valid number."
                    except ValueError:
                        errs[f"key_labs_{lab_name.lower()}"] = "Enter a valid number."
        elif self.step == 4:
            if not self.location_zip:
                errs["location_zip"] = "ZIP code is required."
        return errs

    @rx.event
    def next_step(self):
        errs = self._validate_step()
        self.errors = errs
        if errs:
            return
        self.direction = 1
        self.step = min(self.step + 1, 4)

    @rx.event
    def prev_step(self):
        self.errors = {}
        self.direction = -1
        self.step = max(self.step - 1, 0)

    @rx.event
    def set_cancer_type(self, val: str):
        self.cancer_type = val

    @rx.event
    def set_cancer_stage(self, val: str):
        self.cancer_stage = val

    @rx.event
    def set_biomarkers(self, val: str):
        self.biomarkers = val

    @rx.event
    def set_prior_treatments(self, val: str):
        self.prior_treatments = val

    @rx.event
    def set_lines_of_therapy(self, val: str):
        try:
            self.lines_of_therapy = int(val)
        except ValueError:
            pass

    @rx.event
    def set_age(self, val: str):
        self.age = val

    @rx.event
    def set_sex(self, val: str):
        self.sex = val

    @rx.event
    def set_ecog_score(self, val: str):
        self.ecog_score = val

    @rx.event
    def set_key_labs_wbc(self, val: str):
        self.key_labs_wbc = val

    @rx.event
    def set_key_labs_platelets(self, val: str):
        self.key_labs_platelets = val

    @rx.event
    def set_key_labs_hemoglobin(self, val: str):
        self.key_labs_hemoglobin = val

    @rx.event
    def set_key_labs_creatinine(self, val: str):
        self.key_labs_creatinine = val

    @rx.event
    def set_location_zip(self, val: str):
        self.location_zip = val

    @rx.event
    def set_willing_to_travel(self, val: str):
        try:
            self.willing_to_travel_miles = int(val)
        except ValueError:
            pass

    @rx.event
    def set_additional_conditions(self, val: str):
        self.additional_conditions = val

    @rx.event
    def set_additional_notes(self, val: str):
        self.additional_notes = val

    def _build_patient_payload(self) -> dict:
        biomarkers = [b.strip() for b in self.biomarkers.split(",") if b.strip()] if self.biomarkers else []
        treatments = [t.strip() for t in self.prior_treatments.split(",") if t.strip()] if self.prior_treatments else []
        conditions = [c.strip() for c in self.additional_conditions.split(",") if c.strip()] if self.additional_conditions else []
        key_labs: dict = {}
        for lab_attr, lab_key in [
            ("key_labs_wbc", "wbc"),
            ("key_labs_platelets", "platelets"),
            ("key_labs_hemoglobin", "hemoglobin"),
            ("key_labs_creatinine", "creatinine"),
        ]:
            val = getattr(self, lab_attr)
            if val:
                try:
                    key_labs[lab_key] = float(val)
                except ValueError:
                    pass
        payload: dict = {
            "cancer_type": self.cancer_type,
            "cancer_stage": self.cancer_stage,
            "biomarkers": biomarkers,
            "prior_treatments": treatments,
            "lines_of_therapy": self.lines_of_therapy,
            "age": int(self.age) if self.age else 0,
            "sex": self.sex,
            "location_zip": self.location_zip,
            "willing_to_travel_miles": self.willing_to_travel_miles,
            "additional_conditions": conditions,
            "additional_notes": self.additional_notes or "",
        }
        if self.ecog_score:
            try:
                payload["ecog_score"] = int(self.ecog_score)
            except ValueError:
                pass
        if key_labs:
            payload["key_labs"] = key_labs
        return payload

    @rx.event
    async def submit_form(self):
        errs = self._validate_step()
        self.errors = errs
        if errs:
            return
        patient = self._build_patient_payload()
        from .navigation_state import NavigationState
        nav = await self.get_state(NavigationState)
        nav.previous_view = "intake"
        from .match_state import MatchState
        yield MatchState.start_match(patient)
