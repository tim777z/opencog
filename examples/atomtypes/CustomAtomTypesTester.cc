/*
 * examples/modules/CustomAtomTypesTester.cc
 *
 * Copyright (C) 2008 by Singularity Institute for Artificial Intelligence
 * All Rights Reserved
 *
 * Written by Gustavo Gama <gama@vettalabs.com>
 *
 * This program is free software; you can redistribute it and/or modify
 * it under the terms of the GNU Affero General Public License v3 as
 * published by the Free Software Foundation and including the exceptions
 * at http://opencog.org/wiki/Licenses
 *
 * This program is distributed in the hope that it will be useful,
 * but WITHOUT ANY WARRANTY; without even the implied warranty of
 * MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
 * GNU General Public License for more details.
 *
 * You should have received a copy of the GNU Affero General Public License
 * along with this program; if not, write to:
 * Free Software Foundation, Inc.,
 * 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA.
 */

#include "CustomAtomTypesTester.h"

#include <opencog/atomspace/AtomSpace.h>
#include <opencog/atomspace/Link.h>
#include <opencog/atomspace/Node.h>
#include <opencog/atomspace/types.h>
#include <opencog/server/CogServer.h>
#include <opencog/util/Logger.h>

#include "examples/atomtypes/atom_types.h"

using namespace opencog;

void CustomAtomTypesTester::createAtoms()
{
    logger().info("[CustomAtomTypesTester.createAtoms]");

    AtomSpace& as = server().getAtomSpace();

    Handle number_handle = as.add_node(NUMBER_NODE,"1");
    logger().info("[CustomAtomTypesTester] new node: %s (%d)",
            as.atom_as_string(number_handle).c_str(), number_handle.value());

    Handle foo_handle = as.add_node(FOO_NODE, "foo");
    logger().info("[CustomAtomTypesTester] new node: %s (%d)",
            as.atom_as_string(foo_handle).c_str(), foo_handle.value());

    Handle bar_handle = as.add_node(BAR_NODE, "bar");
    logger().info("[CustomAtomTypesTester] new node: %s (%d)",
            as.atom_as_string(bar_handle).c_str(), bar_handle.value());

    std::vector<Handle> v;
    v.push_back(foo_handle);
    v.push_back(bar_handle);
    Handle foobar_handle = as.add_link(FOOBAR_LINK, v);
    logger().info("[CustomAtomTypesTester] new link: %s (%d)",
            as.atom_as_string(foobar_handle).c_str(), foobar_handle.value());

    Handle list_handle = as.add_link(LIST_LINK, v);
    logger().info("[CustomAtomTypesTester] new link: %s (%d)",
            as.atom_as_string(list_handle).c_str(), list_handle.value());
}

static void dumpHandleSeq(HandleSeq& hs, const char *id)
{
    for( Handle handle: hs) {
        logger().info("[CustomAtomTypesTester] %s: %s",
                id, server().getAtomSpace().atom_as_string(handle).c_str());
    }
}

void CustomAtomTypesTester::dumpAtoms()
{
    logger().info("[CustomAtomTypesTester.dumpAtoms]");
    AtomSpace& as = server().getAtomSpace();
    HandleSeq hs;
    as.get_handles_by_type(back_inserter(hs), BAR_NODE);
    dumpHandleSeq(hs, "bar node");
    hs.clear();
    as.get_handles_by_type(back_inserter(hs), NODE, true);
    dumpHandleSeq(hs, "node");
    hs.clear();
    as.get_handles_by_type(back_inserter(hs), FOOBAR_LINK);
    dumpHandleSeq(hs, "foobar link");
    hs.clear();
    as.get_handles_by_type(back_inserter(hs), UNORDERED_LINK, true);
    dumpHandleSeq(hs, "unordered link");
    hs.clear();
    as.get_handles_by_type(back_inserter(hs), LINK, true);
    dumpHandleSeq(hs, "link");
    hs.clear();
}
