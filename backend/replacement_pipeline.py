class ReplacementPipeline:
    def build_plan(self, job):
        return job

    def execute(self, job, selected_segments=None, progress=None):
        return job

    def concat(self, job):
        return job
