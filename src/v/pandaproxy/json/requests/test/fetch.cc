// Copyright 2020 Vectorized, Inc.
//
// Use of this software is governed by the Business Source License
// included in the file licenses/BSL.md
//
// As of the Change Date specified in that file, in accordance with
// the Business Source License, use of this software will be governed
// by the Apache License, Version 2.0

#include "pandaproxy/json/requests/fetch.h"

#include "kafka/requests/fetch_request.h"
#include "kafka/requests/response.h"
#include "kafka/requests/response_writer.h"
#include "kafka/requests/response_writer_utils.h"
#include "model/fundamental.h"
#include "model/record.h"
#include "model/timestamp.h"
#include "pandaproxy/client/test/utils.h"
#include "pandaproxy/json/requests/fetch.h"
#include "pandaproxy/json/rjson_util.h"
#include "pandaproxy/json/types.h"
#include "seastarx.h"

#include <seastar/testing/thread_test_case.hh>

#include <boost/test/tools/interface.hpp>
#include <boost/test/tools/old/interface.hpp>
#include <rapidjson/stringbuffer.h>
#include <rapidjson/writer.h>

#include <type_traits>

namespace ppj = pandaproxy::json;

iobuf make_record_set(model::offset offset, size_t count) {
    iobuf record_set;
    if (!count) {
        return record_set;
    }
    auto writer{kafka::response_writer(record_set)};
    kafka::writer_serialize_batch(writer, make_batch(offset, count));
    return record_set;
}

auto make_fetch_response(
  model::topic_partition tp, model::offset offset, size_t count) {
    kafka::fetch_response::partition res{tp.topic};
    auto batch = make_batch(offset, count);
    iobuf record_set;
    auto writer{kafka::response_writer(record_set)};
    kafka::writer_serialize_batch(writer, std::move(batch));
    res.responses.push_back(kafka::fetch_response::partition_response{
      .id{tp.partition},
      .error = kafka::error_code::none,
      .high_watermark{model::offset{0}},
      .last_stable_offset{model::offset{1}},
      .log_start_offset{model::offset{0}},
      .aborted_transactions{},
      .record_set{make_record_set(offset, count)}});
    return res;
}

SEASTAR_THREAD_TEST_CASE(test_produce_fetch_empty) {
    model::topic_partition tp{model::topic{"topic"}, model::partition_id{1}};
    auto res = make_fetch_response(tp, model::offset{0}, 0);
    auto fmt = ppj::serialization_format::binary_v2;

    rapidjson::StringBuffer str_buf;
    rapidjson::Writer<rapidjson::StringBuffer> w(str_buf);
    ppj::rjson_serialize_fmt(fmt)(w, std::move(res));

    auto expected = R"([])";

    BOOST_REQUIRE_EQUAL(str_buf.GetString(), expected);
}

SEASTAR_THREAD_TEST_CASE(test_produce_fetch_one) {
    model::topic_partition tp{model::topic{"topic"}, model::partition_id{1}};
    auto res = make_fetch_response(tp, model::offset{0}, 1);
    auto fmt = ppj::serialization_format::binary_v2;

    rapidjson::StringBuffer str_buf;
    rapidjson::Writer<rapidjson::StringBuffer> w(str_buf);
    ppj::rjson_serialize_fmt(fmt)(w, std::move(res));

    auto expected
      = R"([{"topic":"topic","key":"AAAAAAAAAAA=","value":"","partition":1,"offset":0}])";

    BOOST_REQUIRE_EQUAL(str_buf.GetString(), expected);
}