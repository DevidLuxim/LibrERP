# -*- coding:utf-8 -*-
##############################################################################
#
#    OpenERP, Open Source Management Solution
#    Copyright (c) 2013-2015 Didotech srl (<http://www.didotech.com>)
#
#    This program is free software: you can redistribute it and/or modify
#    it under the terms of the GNU General Public License as published by
#    the Free Software Foundation, either version 3 of the License, or
#    (at your option) any later version.
#
#    This program is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU General Public License for more details.
#
#    You should have received a copy of the GNU General Public License
#    along with this program.  If not, see <http://www.gnu.org/licenses/>.
#
##############################################################################

from openerp.osv import orm, fields


class stock_picking(orm.Model):
    """Modificamos la creación de factura desde albarán para incluir el comportamiento de comisiones"""

    _inherit = 'stock.picking'

    def _invoice_hook(self, cr, uid, picking, invoice_id):
        '''Call after the creation of the invoice'''
        res = super(stock_picking, self)._invoice_hook(cr, uid, picking, invoice_id)
        invoice = self.pool['account.invoice'].browse(cr, uid, invoice_id)
        if not invoice.fiscal_position:
            if invoice.partner_id.property_account_position:
                invoice.write({'fiscal_position': invoice.partner_id.property_account_position.id})
        if not invoice.payment_term:
            if invoice.partner_id.property_payment_term:
                invoice.write({'payment_term': invoice.partner_id.property_payment_term.id})
        if picking.sale_id:
            for invoice in picking.sale_id.invoice_ids:
                if invoice.advance_order_id:
                    for line in invoice.invoice_line:
                        self.pool['account.invoice.line'].copy(cr, uid, line.id, {'invoice_id': invoice_id, 'price_unit': -line.price_unit, 'sequence': 1000})
                    invoice.write({'advance_order_id': False})
                    invoice.button_compute()
        return res