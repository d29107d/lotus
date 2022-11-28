import React, { FC, useState, useEffect, useRef } from "react";

import {
  ProTable,
  ProFormInstance,
  ProColumns,
} from "@ant-design/pro-components";
import { Button, Tag, Tooltip } from "antd";
import { useNavigate } from "react-router-dom";
import { MetricType } from "../../types/metric-type";
import { Metrics } from "../../api/api";

const colorMap = new Map<string, string>([
  ["count", "green"],
  ["sum", "blue"],
  ["max", "pink"],
  ["min", "purple"],
  ["latest", "orange"],
  ["average", "cyan"],
  ["unique", "geekblue"],
]);

const operatorDisplayMap = new Map<string, string>([
  ["eq", "="],
  ["isin", "is"],
  ["gt", ">"],
  ["gte", ">="],
  ["lt", "<"],
  ["lte", "<="],
  ["isnotin", "is not"],
]);

interface Props {
  metricArray: MetricType[];
}

const MetricTable: FC<Props> = ({ metricArray }) => {
  const navigate = useNavigate();
  const formRef = useRef<ProFormInstance>();
  var filters: any[];

  const mergeFilters = (
    numeric_filters: any[] | undefined,
    categorical_filters: any[] | undefined
  ) => {
    console.log(numeric_filters, categorical_filters);
    if (numeric_filters !== undefined && categorical_filters === undefined) {
      filters = numeric_filters.map((filter) => {
        return {
          ...filter,
          operator: operatorDisplayMap.get(filter.operator),
        };
      });
    } else if (
      categorical_filters !== undefined &&
      numeric_filters === undefined
    ) {
      filters = categorical_filters.map((filter) => {
        return {
          ...filter,
          operator: operatorDisplayMap.get(filter.operator),
        };
      });
    } else if (
      numeric_filters !== undefined &&
      categorical_filters !== undefined
    ) {
      filters = numeric_filters.map((filter) => {
        return {
          ...filter,
          operator: operatorDisplayMap.get(filter.operator),
        };
      });
      filters = filters.concat(
        categorical_filters.map((filter) => {
          return {
            ...filter,
            operator: operatorDisplayMap.get(filter.operator),
          };
        })
      );
    }

    return filters;
  };

  const columns: ProColumns<MetricType>[] = [
    {
      width: 10,
    },
    {
      title: "Metric Name",
      width: 100,
      dataIndex: "billable_metric_name",
      align: "left",
    },
    {
      title: "Is Cost",
      dataIndex: "billable_metric_name",
      align: "left",
      width: 30,
      render: (_, record) => (
        <div className="self-center">
          {record.is_cost_metric === true && <Tag>Cost</Tag>}
        </div>
      ),
    },
    {
      title: "Type",
      width: 100,
      dataIndex: "metric_type",
      align: "left",
      render: (_, record) => {
        {
          if (record.metric_type === "stateful") {
            return <p>continuous</p>;
          }
          return <p>counter</p>;
        }
      },
    },
    {
      title: "Event Name",
      width: 120,
      dataIndex: "event_name",
      align: "left",
    },
    {
      title: "Aggregation Type",
      width: 120,
      dataIndex: "usage_aggregation_type",
      render: (_, record) => (
        <Tag color={colorMap.get(record.usage_aggregation_type)}>
          {record.usage_aggregation_type}
        </Tag>
      ),
    },
    {
      title: "Property Name",
      width: 120,
      dataIndex: "property_name",
      align: "left",
    },
    {
      title: "Filters",
      width: 150,
      align: "left",
      render: (_, record) => {
        {
          const filters = mergeFilters(
            record.numeric_filters,
            record.categorical_filters
          );

          if (filters) {
            return (
              <div className="space-y-2">
                {filters.map((filter) => (
                  <Tag color="" key={filter.property_name}>
                    {<b>{filter.property_name}</b>} {filter.operator} {'"'}
                    {filter.comparison_value}
                    {'"'}
                  </Tag>
                ))}
              </div>
            );
          }
        }
      },
    },
  ];

  return (
    <div className="border-2 border-solid rounded border-[#EAEAEB]">
      <ProTable<MetricType>
        columns={columns}
        dataSource={metricArray}
        toolBarRender={false}
        rowKey="customer_id"
        formRef={formRef}
        search={false}
        className="w-full"
        pagination={{
          showTotal: (total, range) => (
            <div>{`${range[0]}-${range[1]} of ${total} total items`}</div>
          ),
        }}
        options={false}
      />
    </div>
  );
};

export default MetricTable;
