# mysite/admin/catalogue.py

class ProductItemInline(admin.StackedInline):
    model  = ProductItem
    extra  = 0
    fields = ('price', 'compare_price', 'currency', 'sku',
              'weight_g', 'stock_quantity', 'short_description',
              'care_instructions', 'attributes')

class SongItemInline(admin.StackedInline):
    model  = SongItem
    extra  = 0
    fields = ('artist', 'album', 'duration_s', 'bpm',
              'genre', 'audio_url', 'preview_url', 'attributes')

class ItemAdmin(admin.ModelAdmin):
    list_display = ('item_id', 'client', 'name', 'domain', 'status')
    list_filter  = ('domain', 'status', 'client')
    inlines      = [
        ProductItemInline,   # only one will have data depending on domain
        SongItemInline,
        DocumentItemInline,
        ServiceItemInline,
        ItemTaxonomyNodeInline,
        ItemImageInline,
    ]