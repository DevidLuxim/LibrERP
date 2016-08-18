# -*- encoding: utf-8 -*-
##############################################################################
#
#    OpenERP, Open Source Management Solution
#
#    Copyright (C) 2014-2016 Didotech srl (<http://www.didotech.com>).
#
#                       All Rights Reserved
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

{
    "name": "Purchase Order Filter",
    "version": "3.1.1.1",
    "author": "Didotech SRL",
    "website": "http://www.didotech.com",
    "category": 'Accounting & Finance',
    "description": """
        Module adds extra functionality to purchase_order:
            - possibility to filter order by year
            - possibility to see sale of last or current month
            - search by sales team includes children
    """,
    "depends": [
        'sale',
    ],
    "init_xml": [],
    "update_xml": [
        'purchase_order_view.xml'
    ],
    "active": False,
    "installable": True,
    'auto_install': True,
}