

# Register your models here.
class SoftDeleteAdminMixin:
    """Show soft-deleted rows in the admin.

    The default manager filters them out, which is correct for the API but wrong
    for an operations panel. Combined with `is_deleted` in list_filter, staff can
    switch between live and deleted records.
    """

    def get_queryset(self, request):
        return self.model.all_objects.all()
