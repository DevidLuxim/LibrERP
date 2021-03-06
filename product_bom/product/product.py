# -*- coding: utf-8 -*-
##############################################################################
#
#    Copyright (C) 2013-2014 Didotech srl (info@didotech.com)
#    All Rights Reserved
#
#    This program is free software: you can redistribute it and/or modify
#    it under the terms of the GNU Affero General Public License as published
#    by the Free Software Foundation, either version 3 of the License, or
#    (at your option) any later version.
#
#    This program is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU General Public License for more details.
#
#    You should have received a copy of the GNU Affero General Public License
#    along with this program.  If not, see <http://www.gnu.org/licenses/>.
#
##############################################################################

from openerp.osv import orm, fields
from openerp.tools.translate import _
from openerp import tools
from datetime import datetime
from openerp.tools import DEFAULT_SERVER_DATE_FORMAT
import decimal_precision as dp

import time

import logging
_logger = logging.getLogger(__name__)
_logger.setLevel(logging.DEBUG)

ENABLE_CACHE = True

class product_product(orm.Model):
    """
    Inherit Product in order to add an "Bom Stock" field
    """
    _inherit = 'product.product'
    
    # def _get_prefered_supplier(self, cr, uid, ids, field_name, args, context):
    #     res = {}
    #     for line in self.browse(cr, uid, ids, context):
    #         res[line.id] = line.seller_ids and line.seller_ids[0].name.id or False
    #     return res

    def __init__(self, cr, uid):
        super(product_product, self).__init__(cr, uid)
        self.product_cost_cache = {}

    def _compute_purchase_price(self, cr, uid, ids,
                                product_uom=None,
                                bom_properties=None,
                                context=None):
        '''
        Compute the purchase price, taking into account sub products and routing
        '''

        context = context or self.pool['res.users'].context_get(cr, uid)
        bom_properties = bom_properties or []
        user = self.pool['res.users'].browse(cr, uid, uid, context)
        
        bom_obj = self.pool['mrp.bom']
        uom_obj = self.pool['product.uom']

        res = {}
        ids = ids or []
        
        for product in self.browse(cr, uid, ids, context):
            # print(u'{product.id}: {product.name}'.format(product=product))
            bom_id = bom_obj._bom_find(cr, uid, product.id, product_uom=None, properties=bom_properties)
            if bom_id:
                sub_bom_ids = bom_obj.search(cr, uid, [('bom_id', '=', bom_id)], context=context)
                sub_products = bom_obj.browse(cr, uid, sub_bom_ids, context)
                
                price = 0.
                
                for sub_product in sub_products:
                    if sub_product.product_id.id == product.id:
                        error = "Product '{product.name}' (id: {product.id}) is referenced to itself".format(product=product)
                        _logger.error(error)
                        continue
                        
                    # std_price = sub_product.standard_price
                    if ENABLE_CACHE:
                        if sub_product.product_id.id in self.product_cost_cache:
                            std_price = self.product_cost_cache[sub_product.product_id.id]
                        else:
                            std_price = sub_product.product_id.cost_price
                            self.product_cost_cache[sub_product.product_id.id] = std_price
                    else:
                        std_price = sub_product.product_id.cost_price

                    qty = uom_obj._compute_qty(cr, uid,
                                               from_uom_id=sub_product.product_uom.id,
                                               qty=sub_product.product_qty,
                                               to_uom_id=sub_product.product_id.uom_po_id.id)
                    price += std_price * qty
                    # if sub_product.routing_id:
                    #     for wline in sub_product.routing_id.workcenter_lines:
                    #         wc = wline.workcenter_id
                    #         cycle = wline.cycle_nbr
                    #         # hour = (wc.time_start + wc.time_stop + cycle * wc.time_cycle) * (wc.time_efficiency or 1.0)
                    #         price += wc.costs_cycle * cycle + wc.costs_hour * wline.hour_nbr

                if sub_products:
                    # Don't use browse when we already have it
                    bom = sub_products[0].bom_id
                else:
                    bom = bom_obj.browse(cr, uid, bom_id, context)
                
                if bom.routing_id:
                    for wline in bom.routing_id.workcenter_lines:
                        wc = wline.workcenter_id
                        cycle = wline.cycle_nbr
                        # hour = (wc.time_start + wc.time_stop + cycle * wc.time_cycle) * (wc.time_efficiency or 1.0)
                        price += wc.costs_cycle * cycle + wc.costs_hour * wline.hour_nbr
                price /= bom.product_qty
                price = uom_obj._compute_price(cr, uid, bom.product_uom.id, price, bom.product_id.uom_id.id)
                res[product.id] = price
            else:
                # no BoM: use standard_price
                # use standard_price if no supplier indicated

                if product.id in self.product_cost_cache and ENABLE_CACHE:
                    res[product.id] = self.product_cost_cache[product.id]
                    continue

                if product.prefered_supplier:
                    pricelist = product.prefered_supplier.property_product_pricelist_purchase or False
                    ctx = {
                        'date': time.strftime(DEFAULT_SERVER_DATE_FORMAT)
                    }
                    price = self.pool['product.pricelist'].price_get(cr, uid, [pricelist.id], product.id, 1, context=ctx)[pricelist.id] or 0

                    price_subtotal = 0.0
                    if pricelist:
                        from_currency = pricelist.currency_id.id
                        to_currency = user.company_id.currency_id.id
                        price_subtotal = self.pool['res.currency'].compute(
                            cr, uid,
                            from_currency_id=from_currency,
                            to_currency_id=to_currency,
                            from_amount=price,
                            context=context
                        )

                    res[product.id] = price_subtotal or price
                else:
                    res[product.id] = product.standard_price

                if ENABLE_CACHE:
                    self.product_cost_cache[product.id] = res[product.id]
                continue
        
        return res

    def get_cost_field(self, cr, uid, ids, context=None):
        start_time = datetime.now()
        context = context or self.pool['res.users'].context_get(cr, uid)
        end_time = datetime.now()
        duration_seconds = (end_time - start_time)
        duration = '{sec}'.format(sec=duration_seconds)
        _logger.info(u'get_cost_field get in {duration} for {id}'.format(duration=duration, id=ids))
        res = self._cost_price(cr, uid, ids, '', [], context)
        return res

    def _cost_price(self, cr, uid, ids, field_name, arg, context=None):
        start_time = datetime.now()
        # _logger.error(
        #     u'START _cost_price for {ids} and {field}'.format(ids=ids, field=field_name))
        context = context or self.pool['res.users'].context_get(cr, uid)
        product_uom = context.get('product_uom')
        bom_properties = context.get('properties')
        res = self._compute_purchase_price(cr, uid, ids, product_uom, bom_properties, context)
        end_time = datetime.now()
        duration_seconds = (end_time - start_time)
        duration = '{sec}'.format(sec=duration_seconds)
        _logger.info(u'_cost_price get in {duration}'.format(duration=duration))
        return res

    def _kit_filter(self, cr, uid, obj, name, args, context):
        if not args:
            return []
        bom_obj = self.pool['mrp.bom']
        for search in args:
            if search[0] == 'is_kit':
                if search[2]:
                    bom_ids = bom_obj.search(cr, uid, [('bom_id', '=', False)], context=context)
                    if bom_ids:
                        res = [bom.product_id.id for bom in bom_obj.browse(cr, uid, bom_ids, context)]
                        return [('id', 'in', res)]
                    else:
                        return [('id', 'in', [])]
        return []
    
    def _is_kit(self, cr, uid, ids, product_uom=None, bom_properties=None, context=None):
        if not len(ids):
            return []
        '''
        Show if have or not a bom
        '''
        start_time = datetime.now()
        context = context or self.pool['res.users'].context_get(cr, uid)
        bom_properties = bom_properties or []

        bom_obj = self.pool['mrp.bom']

        res = {}
        ids = ids or []

        for product in self.browse(cr, uid, ids, context):
            bom_id = bom_obj._bom_find(cr, uid, product.id, product_uom=None, properties=bom_properties)
            # cr.execute("""SELECT id FROM mrp_bom WHERE product_id={product_id}""".format(product_id=product.id))
            # bom_id = cr.fetchall()
            if not bom_id:
                res[product.id] = False
            else:
                res[product.id] = True
        end_time = datetime.now()
        duration_seconds = (end_time - start_time)
        duration = '{sec}'.format(sec=duration_seconds)
        _logger.info(u'IS KIT get in {duration}'.format(duration=duration))
        return res
    
    """
    Inherit Product in order to add an "Bom Stock" field
    """
    def _bom_stock_mapping(self, cr, uid, context=None):
        return {'real': 'qty_available',
                'virtual': 'virtual_available',
                'immediately': 'immediately_usable_qty'}

    def _compute_bom_stock(self, cr, uid, product,
                           quantities, company, context=None):
        context = context or self.pool['res.users'].context_get(cr, uid)
        bom_obj = self.pool['mrp.bom']
        uom_obj = self.pool['product.uom']
        mapping = self._bom_stock_mapping(cr, uid, context=context)
        stock_field = mapping[company.ref_stock]

        product_qty = quantities.get(stock_field, 0.0)
        # find a bom on the product
        bom_id = bom_obj._bom_find(
            cr, uid, product.id, product.uom_id.id, properties=[])

        if bom_id:
            prod_min_quantities = []
            bom = bom_obj.browse(cr, uid, bom_id, context=context)
            if bom.bom_lines:
                stop_compute_bom = False
                # Compute stock qty of each product used in the BoM and
                # get the minimal number of items we can produce with them
                for line in bom.bom_lines:
                    prod_min_quantity = 0.0
                    bom_qty = line.product_id[stock_field] # expressed in product UOM
                    # the reference stock of the component must be greater
                    # than the quantity of components required to
                    # build the bom
                    line_product_qty = uom_obj._compute_qty_obj(cr, uid,
                                                                line.product_uom,
                                                                line.product_qty,
                                                                line.product_id.uom_id,
                                                                context=context)

                    if line_product_qty and (bom_qty > line_product_qty):
                        prod_min_quantity = bom_qty / line_product_qty  # line.product_qty is always > 0
                    else:
                        # if one product has not enough stock,
                        # we do not need to compute next lines
                        # because the final quantity will be 0.0 in any case
                        stop_compute_bom = True

                    prod_min_quantities.append(prod_min_quantity)
                    if stop_compute_bom:
                        break
            produced_qty = uom_obj._compute_qty_obj(cr, uid,
                                                    bom.product_uom,
                                                    bom.product_qty,
                                                    bom.product_id.uom_id,
                                                    context=context)
            if prod_min_quantities:
                product_qty += min(prod_min_quantities) * produced_qty
            else:
                product_qty += produced_qty
        return product_qty

    def _product_available(self, cr, uid, ids, field_names=[],
                           arg=False, context=None):
        # We need available, virtual or immediately usable
        # quantity which is selected from company to compute Bom stock Value
        # so we add them in the calculation.
        context = context or self.pool['res.users'].context_get(cr, uid)
        start_time = datetime.now()
        user_obj = self.pool['res.users']
        comp_obj = self.pool['res.company']
        if 'bom_stock' in field_names:
            field_names.append('qty_available')
            field_names.append('immediately_usable_qty')
            field_names.append('virtual_available')

        res = super(product_product, self)._product_available(cr, uid, ids, field_names, arg, context)

        if 'bom_stock' in field_names:
            company = user_obj.browse(cr, uid, uid, context=context).company_id
            if not company:
                company_id = comp_obj.search(cr, uid, [], context=context)[0]
                company = comp_obj.browse(cr, uid, company_id, context=context)

            for product_id, stock_qty in res.iteritems():
                product = self.browse(cr, uid, product_id, context=context)
                res[product_id]['bom_stock'] = self._compute_bom_stock(cr, uid, product, stock_qty, company, context=context)
        end_time = datetime.now()
        duration_seconds = (end_time - start_time)
        duration = '{sec}'.format(sec=duration_seconds)
        _logger.info(u'_product_available get in {duration}'.format(duration=duration))
        return res
    
    def _get_boms(self, cr, uid, ids, field_name, arg, context):
        result = {}
        
        for product_id in ids:
            result[product_id] = self.pool['mrp.bom'].search(cr, uid, [('product_id', '=', product_id), ('bom_id', '=', False)], context=context)
        
        return result
    
    def price_get(self, cr, uid, ids, ptype='list_price', context=None):
        start_time = datetime.now()
        context = context or self.pool['res.users'].context_get(cr, uid)
        if 'currency_id' in context:
            pricetype_obj = self.pool['product.price.type']
            price_type_id = pricetype_obj.search(cr, uid, [('field', '=', ptype)], context=context)[0]
            price_type_currency_id = pricetype_obj.browse(cr, uid, price_type_id, context).currency_id.id

        res = {}
        product_uom_obj = self.pool['product.uom']
        for product in self.browse(cr, uid, ids, context=context):
            res[product.id] = product[ptype] or 0.0

            if ptype == 'standard_price' and product.is_kit:
                res[product.id] = product.cost_price or product.standard_price

            if ptype == 'list_price':
                res[product.id] = (res[product.id] * (product.price_margin or 1.0)) + product.price_extra
            if 'uom' in context:
                uom = product.uom_id or product.uos_id
                res[product.id] = product_uom_obj._compute_price(cr, uid,
                                                                 uom.id, res[product.id], context['uom'])
            # Convert from price_type currency to asked one
            if 'currency_id' in context:
                # Take the price_type currency from the product field
                # This is right cause a field cannot be in more than one currency
                res[product.id] = self.pool['res.currency'].compute(cr, uid, price_type_currency_id,
                                                                        context['currency_id'], res[product.id], context=context)
        end_time = datetime.now()
        duration_seconds = (end_time - start_time)
        duration = '{sec}'.format(sec=duration_seconds)
        _logger.info(u'price_get get in {duration}'.format(duration=duration))
        return res
        
    _columns = {
        'date_inventory': fields.function(lambda *a, **k: {}, method=True, type='date', string="Date Inventory"),
        'cost_price': fields.function(_cost_price,
                                      method=True,
                                      string=_('Cost Price (incl. BoM)'),
                                      digits_compute=dp.get_precision('Purchase Price'),
                                      help="The cost price is the standard price or, if the product has a bom, "
                                      "the sum of all standard price of its components. it take also care of the "
                                      "bom costing like cost per cylce."),
        'prefered_supplier': fields.related('seller_ids', 'name', type='many2one', relation='res.partner', string='Prefered Supplier'),
        'is_kit': fields.function(_is_kit, fnct_search=_kit_filter, method=True, type="boolean", string="Kit"),
        'bom_lines': fields.function(_get_boms, relation='mrp.bom', string='Boms', type='one2many', method=True),
        'qty_available': fields.function(
            _product_available,
            multi='qty_available',
            type='float',
            digits_compute=dp.get_precision('Product UoM'),
            string='Quantity On Hand',
            help="Current quantity of products.\n"
                 "In a context with a single Stock Location, this includes "
                 "goods stored at this Location, or any of its children.\n"
                 "In a context with a single Warehouse, this includes "
                 "goods stored in the Stock Location of this Warehouse, "
                 "or any "
                 "of its children.\n"
                 "In a context with a single Shop, this includes goods "
                 "stored in the Stock Location of the Warehouse of this Shop, "
                 "or any of its children.\n"
                 "Otherwise, this includes goods stored in any Stock Location "
                 "typed as 'internal'."),
        'virtual_available': fields.function(
            _product_available,
            multi='qty_available',
            type='float',
            digits_compute=dp.get_precision('Product UoM'),
            string='Quantity Available',
            help="Forecast quantity (computed as Quantity On Hand "
                 "- Outgoing + Incoming)\n"
                 "In a context with a single Stock Location, this includes "
                 "goods stored at this Location, or any of its children.\n"
                 "In a context with a single Warehouse, this includes "
                 "goods stored in the Stock Location of this Warehouse, "
                 "or any "
                 "of its children.\n"
                 "In a context with a single Shop, this includes goods "
                 "stored in the Stock Location of the Warehouse of this Shop, "
                 "or any of its children.\n"
                 "Otherwise, this includes goods stored in any Stock Location "
                 "typed as 'internal'."),
        'incoming_qty': fields.function(
            _product_available,
            multi='qty_available',
            type='float',
            digits_compute=dp.get_precision('Product UoM'),
            string='Incoming',
            help="Quantity of products that are planned to arrive.\n"
                 "In a context with a single Stock Location, this includes "
                 "goods arriving to this Location, or any of its children.\n"
                 "In a context with a single Warehouse, this includes "
                 "goods arriving to the Stock Location of this Warehouse, or "
                 "any of its children.\n"
                 "In a context with a single Shop, this includes goods "
                 "arriving to the Stock Location of the Warehouse of this "
                 "Shop, or any of its children.\n"
                 "Otherwise, this includes goods arriving to any Stock "
                 "Location typed as 'internal'."),
        'outgoing_qty': fields.function(
            _product_available,
            multi='qty_available',
            type='float',
            digits_compute=dp.get_precision('Product UoM'),
            string='Outgoing',
            help="Quantity of products that are planned to leave.\n"
                 "In a context with a single Stock Location, this includes "
                 "goods leaving from this Location, or any of its children.\n"
                 "In a context with a single Warehouse, this includes "
                 "goods leaving from the Stock Location of this Warehouse, or "
                 "any of its children.\n"
                 "In a context with a single Shop, this includes goods "
                 "leaving from the Stock Location of the Warehouse of this "
                 "Shop, or any of its children.\n"
                 "Otherwise, this includes goods leaving from any Stock "
                 "Location typed as 'internal'."),
        'immediately_usable_qty': fields.function(
            _product_available,
            digits_compute=dp.get_precision('Product UoM'),
            type='float',
            string='Immediately Usable',
            multi='qty_available',
            help="Quantity of products really available for sale." \
                 "Computed as: Quantity On Hand - Outgoing."),
        'bom_stock': fields.function(
            _product_available,
            digits_compute=dp.get_precision('Product UoM'),
            type='float',
            string='Bill of Materials Stock',
            help="Quantities of products based on Bill of Materials, "
                 "useful to know how much of this "
                 "product you could produce. "
                 "Computed as:\n "
                 "Reference stock of this product + "
                 "how much could I produce of this product with the BoM"
                 "Components",
            multi='qty_available'),
    }

    def copy(self, cr, uid, product_id, default=None, context=None):
        """Copies the product and the BoM of the product"""
        context = context or self.pool['res.users'].context_get(cr, uid)
        copy_id = super(product_product, self).copy(cr, uid, product_id, default, context)

        bom_obj = self.pool['mrp.bom']
        bom_ids = bom_obj.search(cr, uid, [('product_id', '=', product_id), ('bom_id', '=', False)], context=context)
        
        for bom_id in bom_ids:
            bom_obj.copy(cr, uid, bom_id, {'product_id': copy_id}, context=context)
        return copy_id

    def update_product_bom_price(self, cr, uid, ids, context=None):
        """
        This Function is call by scheduler.
        """
        context = context or self.pool['res.users'].context_get(cr, uid)
        for product in self.browse(cr, uid, ids, context):
            product.write({'standard_price': product.cost_price})
        return True

    def update_bom_price(self, cr, uid, context=None):
        """
        This Function is call by scheduler.
        """
        context = context or self.pool['res.users'].context_get(cr, uid)
        # search product with kit
        product_ids = self.search(cr, uid, [('is_kit', '=', True)], context=context)
        for product in self.browse(cr, uid, product_ids, context):
            product.write({'standard_price': product.cost_price})
        return True

    def write(self, cr, uid, ids, vals, context=None):
        context = context or self.pool['res.users'].context_get(cr, uid)

        if not isinstance(ids, (list, tuple)):
            ids = [ids]

        res = super(product_product, self).write(cr, uid, ids, vals, context)

        if ENABLE_CACHE:
            if 'standard_price' in vals:
                changed_product = ids
                bom_obj = self.pool['mrp.bom']
                bom_ids = bom_obj.search(cr, uid, [('product_id', 'in', ids)], context=context)
                for bom in bom_obj.browse(cr, uid, bom_ids, context):
                    bom_parent = bom.bom_id
                    while bom_parent:
                        changed_product.append(bom_parent.product_id.id)
                        bom_parent = bom_parent.bom_id

                for product_id in changed_product:
                    if product_id in self.product_cost_cache:
                        del self.product_cost_cache[product_id]
        return res

# CANCEL CACHE IF SOMETHING CHANGE ON PRICELIST


class product_pricelist_item(orm.Model):

    _inherit = 'product.pricelist.item'

    def create(self, cr, uid, vals, context):
        res = super(product_pricelist_item, self).create(cr, uid, vals, context)
        if ENABLE_CACHE:
            self.pool['product.product'].product_cost_cache = {}
        return res

    def write(self, cr, uid, ids, vals, context):
        res = super(product_pricelist_item, self).write(cr, uid, ids, vals, context)
        if ENABLE_CACHE:
            self.pool['product.product'].product_cost_cache = {}
        return res

    def unlink(self, cr, uid, ids, context):
        res = super(product_pricelist_item, self).unlink(cr, uid, ids, context)
        if ENABLE_CACHE:
            self.pool['product.product'].product_cost_cache = {}
        return res


class res_partner(orm.Model):

    _inherit = 'product.pricelist.item'

    def create(self, cr, uid, vals, context):
        res = super(res_partner, self).create(cr, uid, vals, context)
        if ENABLE_CACHE and 'property_product_pricelist_purchase' in vals:
            self.pool['product.product'].product_cost_cache = {}
        return res

    def write(self, cr, uid, ids, vals, context):
        res = super(res_partner, self).write(cr, uid, ids, vals, context)
        if ENABLE_CACHE and 'property_product_pricelist_purchase' in vals:
            self.pool['product.product'].product_cost_cache = {}
        return res
